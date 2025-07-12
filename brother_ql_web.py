#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
This is a web service to print labels on Brother QL label printers.
"""

import sys
import logging
import random
import json
import argparse
import os
from pathlib import Path
from io import BytesIO
from typing import Dict, List, Tuple, Optional, Any, Union
try:
    import qrcode
    import qrcode.constants
    QR_AVAILABLE = True
except ImportError:
    qrcode = None  # type: ignore
    QR_AVAILABLE = False

from bottle import run, route, get, post, response, request, jinja2_view as view, static_file, redirect
from PIL import Image, ImageDraw, ImageFont

from brother_ql.devicedependent import models, label_type_specs, label_sizes
from brother_ql.devicedependent import ENDLESS_LABEL, DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL
from brother_ql import BrotherQLRaster, create_label
from brother_ql.backends import backend_factory, guess_backend

from font_helpers import get_fonts

logger = logging.getLogger(__name__)

LABEL_SIZES = [(name, label_type_specs[name]['name']) for name in label_sizes]

# Global variables
DEBUG = False
FONTS: Dict[str, Dict[str, str]] = {}
BACKEND_CLASS = None
CONFIG: Dict[str, Any] = {}


def load_config() -> Dict[str, Any]:
    """Load configuration from config files."""
    try:
        with open('config.json', encoding='utf-8') as fh:
            config = json.load(fh)
    except FileNotFoundError:
        with open('config.example.json', encoding='utf-8') as fh:
            config = json.load(fh)

    # Add font whitelist if not present
    if 'FONT_WHITELIST' not in config:
        config['FONT_WHITELIST'] = []

    return config


def get_whitelisted_fonts(font_folder: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """
    Get fonts filtered by whitelist configuration.
    If whitelist is empty, loads all fonts (backward compatibility).
    """
    all_fonts = get_fonts(font_folder)

    if not CONFIG.get('FONT_WHITELIST'):
        # No whitelist configured, return all fonts for backward compatibility
        return all_fonts

    whitelist = set(CONFIG['FONT_WHITELIST'])
    filtered_fonts = {}

    for family, styles in all_fonts.items():
        if family in whitelist:
            filtered_fonts[family] = styles

    if not filtered_fonts:
        logger.warning("Font whitelist filtered out all fonts. Falling back to all available fonts.")
        return all_fonts

    logger.info(f"Loaded {len(filtered_fonts)} font families from whitelist: {list(filtered_fonts.keys())}")
    return filtered_fonts


def get_default_font_config() -> Dict[str, str]:
    """Get default font configuration handling both old and new formats."""
    default_fonts = CONFIG['LABEL']['DEFAULT_FONTS']

    if isinstance(default_fonts, list) and len(default_fonts) > 0:
        return default_fonts[0]
    elif isinstance(default_fonts, dict):
        return default_fonts
    else:
        return {'family': 'Arial', 'style': 'Regular'}


# Initialize configuration
CONFIG = load_config()


@route('/')
def index():
    """Redirect to label designer."""
    redirect('/labeldesigner')


@route('/static/<filename:path>')
def serve_static(filename: str):
    """Serve static files."""
    return static_file(filename, root='./static')


@route('/labeldesigner')
@view('labeldesigner.jinja2')
def labeldesigner():
    """Main label designer page."""
    font_family_names = sorted(list(FONTS.keys()))
    default_font_config = get_default_font_config()

    return {
        'font_family_names': font_family_names,
        'fonts': FONTS,
        'label_sizes': LABEL_SIZES,
        'website': CONFIG['WEBSITE'],
        'label': CONFIG['LABEL'],
        'default_orientation': CONFIG['LABEL'].get('DEFAULT_ORIENTATION', 'standard'),
        'default_font_config': default_font_config
    }


def get_label_context(request) -> Dict[str, Any]:
    """Extract and validate label context from request parameters."""
    try:
        d = request.params.decode()  # UTF-8 decoded form data
    except Exception:
        d = request.forms

    # Parse font family and style
    font_family_full = d.get('font_family', 'Arial (Regular)')
    if '(' in font_family_full:
        font_family = font_family_full.rpartition('(')[0].strip()
        font_style = font_family_full.rpartition('(')[2].rstrip(')')
    else:
        font_family = font_family_full
        font_style = 'Regular'

    context = {
        'text': d.get('text', None),
        'font_size': int(d.get('font_size', 100)),
        'font_family': font_family,
        'font_style': font_style,
        'label_size': d.get('label_size', "62"),
        'kind': label_type_specs[d.get('label_size', "62")]['kind'],
        'margin': int(d.get('margin', 10)),
        'threshold': int(d.get('threshold', 70)),
        'align': d.get('align', 'center'),
        'orientation': d.get('orientation', 'standard'),
        'margin_top': float(d.get('margin_top', 24)) / 100.0,
        'margin_bottom': float(d.get('margin_bottom', 45)) / 100.0,
        'margin_left': float(d.get('margin_left', 35)) / 100.0,
        'margin_right': float(d.get('margin_right', 35)) / 100.0,
        'enable_qr': d.get('enable_qr', 'false').lower() == 'true',
        'qr_data': d.get('qr_data', ''),
        'qr_size': d.get('qr_size', 'medium'),
        'qr_position': d.get('qr_position', 'right'),
    }

    # Convert relative margins to absolute pixels
    context['margin_top'] = int(context['font_size'] * context['margin_top'])
    context['margin_bottom'] = int(context['font_size'] * context['margin_bottom'])
    context['margin_left'] = int(context['font_size'] * context['margin_left'])
    context['margin_right'] = int(context['font_size'] * context['margin_right'])

    # Set fill color based on label type
    context['fill_color'] = (255, 0, 0) if 'red' in context['label_size'] else (0, 0, 0)

    def get_font_path(font_family_name: Optional[str], font_style_name: Optional[str]) -> str:
        """Get font path, falling back to default if not found."""
        try:
            if font_family_name is None or font_style_name is None:
                default_font = get_default_font_config()
                font_family_name = default_font.get('family', 'Arial')
                font_style_name = default_font.get('style', 'Regular')

            font_path = FONTS[font_family_name][font_style_name]
        except KeyError:
            raise LookupError("Couldn't find the font & style")
        return font_path

    context['font_path'] = get_font_path(context['font_family'], context['font_style'])

    def get_label_dimensions(label_size: str) -> Tuple[int, int]:
        """Get label dimensions from label size."""
        try:
            ls = label_type_specs[label_size]
        except KeyError:
            raise LookupError("Unknown label_size")
        return ls['dots_printable']

    width, height = get_label_dimensions(context['label_size'])
    if height > width:
        width, height = height, width
    if context['orientation'] == 'rotated':
        height, width = width, height
    context['width'], context['height'] = width, height

    return context


def create_label_im(text: str, **kwargs) -> Image.Image:
    """Create label image from text and parameters."""
    label_type = kwargs['kind']
    im_font = ImageFont.truetype(kwargs['font_path'], kwargs['font_size'])
    im = Image.new('L', (20, 20), 'white')
    draw = ImageDraw.Draw(im)

    # Generate QR code if enabled
    qr_img: Any = None
    qr_size_px = 0
    if kwargs.get('enable_qr', False) and kwargs.get('qr_data', '').strip() and QR_AVAILABLE and qrcode:
        qr_size_map = {'small': 4, 'medium': 6, 'large': 8}
        box_size = qr_size_map.get(kwargs.get('qr_size', 'medium'), 6)

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=box_size,
            border=2,
        )
        qr.add_data(kwargs['qr_data'])
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_size_px = getattr(qr_img, 'size', [0])[0]
    elif kwargs.get('enable_qr', False) and not QR_AVAILABLE:
        logger.warning("QR code generation requested but qrcode package not available")

    # Workaround for multiline_textsize() bug with empty lines
    lines = [line if line else ' ' for line in text.split('\n')]
    text = '\n'.join(lines)

    # Handle PIL version compatibility for text size calculation
    textsize = get_text_size(draw, text, im_font)

    # Adjust dimensions for QR code
    qr_spacing = 10 if qr_img else 0
    effective_text_width = textsize[0]
    if qr_img:
        effective_text_width = textsize[0] + qr_size_px + qr_spacing

    width, height = kwargs['width'], kwargs['height']

    # Adjust height for endless labels
    if kwargs['orientation'] == 'standard' and label_type == ENDLESS_LABEL:
        height = max(textsize[1], qr_size_px if qr_img else 0) + kwargs['margin_top'] + kwargs['margin_bottom']
    elif kwargs['orientation'] == 'rotated' and label_type == ENDLESS_LABEL:
        width = effective_text_width + kwargs['margin_left'] + kwargs['margin_right']

    im = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(im)

    # Calculate text and QR code positions
    text_pos, qr_pos = calculate_positions(
        width, height, textsize, qr_size_px, kwargs, label_type
    )

    # Draw text
    draw.multiline_text(text_pos, text, kwargs['fill_color'], font=im_font, align=kwargs['align'])

    # Draw QR code if available
    if qr_img and qr_pos:
        if hasattr(qr_img, 'mode') and qr_img.mode != 'RGB':
            qr_img = qr_img.convert('RGB')
        im.paste(qr_img, qr_pos)  # type: ignore

    return im


def get_text_size(draw: Any, text: str, font: Any) -> Tuple[int, int]:
    """Get text size with PIL version compatibility."""
    try:
        # PIL 10.0.0+ uses textbbox (preferred method)
        bbox = draw.multiline_textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except AttributeError:
        try:
            # PIL 8.0.0+ uses textsize (deprecated but still works)
            return draw.multiline_textsize(text, font=font)  # type: ignore
        except AttributeError:
            # Manual calculation for very old PIL versions
            result = estimate_text_size(draw, text, font)
            return (int(result[0]), int(result[1]))


def estimate_text_size(draw: Any, text: str, font: Any) -> Tuple[int, int]:
    """Estimate text size for very old PIL versions."""
    lines = text.split('\n')
    max_width = 0
    line_height = getattr(font, 'size', 12)
    total_height = 0

    for line in lines:
        try:
            # Try single line textbbox
            line_bbox = draw.textbbox((0, 0), line, font=font)
            line_width = line_bbox[2] - line_bbox[0]
        except AttributeError:
            try:
                # Try single line textsize
                line_width = draw.textsize(line, font=font)[0]  # type: ignore
            except AttributeError:
                # Character-based estimation
                line_width = len(line) * int(line_height * 0.6)

        max_width = max(max_width, line_width)
        total_height += line_height

    return (int(max_width), int(total_height))


def calculate_positions(width: int, height: int, textsize: Tuple[int, int],
                       qr_size_px: int, kwargs: Dict[str, Any],
                       label_type) -> Tuple[Tuple[int, int], Optional[Tuple[int, int]]]:
    """Calculate text and QR code positions."""
    qr_spacing = 10 if qr_size_px > 0 else 0
    qr_pos = None

    horizontal_offset = 0
    vertical_offset = 0

    if kwargs['orientation'] == 'standard':
        # Vertical offset
        if label_type in (DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL):
            vertical_offset = (height - textsize[1]) // 2
            vertical_offset += (kwargs['margin_top'] - kwargs['margin_bottom']) // 2
        else:
            vertical_offset = kwargs['margin_top']

        # Horizontal positioning with QR code
        if qr_size_px > 0:
            qr_position = kwargs.get('qr_position', 'right')
            if qr_position == 'left':
                horizontal_offset = kwargs['margin_left'] + qr_size_px + qr_spacing
                qr_x = kwargs['margin_left']
            elif qr_position == 'right':
                horizontal_offset = kwargs['margin_left']
                qr_x = width - qr_size_px - kwargs['margin_right']
            else:  # center
                total_content_width = textsize[0] + qr_size_px + qr_spacing
                start_x = (width - total_content_width) // 2
                horizontal_offset = start_x
                qr_x = start_x + textsize[0] + qr_spacing

            qr_y = (height - qr_size_px) // 2
            qr_pos = (int(qr_x), int(qr_y))
        else:
            horizontal_offset = max((width - textsize[0]) // 2, 0)

    else:  # rotated
        vertical_offset = (height - textsize[1]) // 2
        vertical_offset += (kwargs['margin_top'] - kwargs['margin_bottom']) // 2

        if label_type in (DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL):
            effective_width = textsize[0] + (qr_size_px + qr_spacing if qr_size_px > 0 else 0)
            horizontal_offset = max((width - effective_width) // 2, 0)
        else:
            horizontal_offset = kwargs['margin_left']

        # Position QR code for rotated orientation
        if qr_size_px > 0:
            qr_x = horizontal_offset + textsize[0] + qr_spacing
            qr_y = (height - qr_size_px) // 2
            qr_pos = (int(qr_x), int(qr_y))

    return (int(horizontal_offset), int(vertical_offset)), qr_pos


@get('/api/preview/text')
@post('/api/preview/text')
def get_preview_image():
    """Get preview image of the label."""
    try:
        context = get_label_context(request)
        im = create_label_im(**context)
        return_format = getattr(request.query, 'get', lambda x, y: y)('return_format', 'png')

        if return_format == 'base64':
            import base64
            response.set_header('Content-type', 'text/plain')
            return base64.b64encode(image_to_png_bytes(im))
        else:
            response.set_header('Content-type', 'image/png')
            return image_to_png_bytes(im)
    except Exception as e:
        logger.error(f"Preview generation failed: {e}")
        response.status = 500
        return {'error': str(e)}


def image_to_png_bytes(im: Image.Image) -> bytes:
    """Convert PIL image to PNG bytes."""
    image_buffer = BytesIO()
    im.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return image_buffer.read()


@post('/api/print/text')
@get('/api/print/text')
def print_text():
    """Print a text label."""
    return_dict: Dict[str, Any] = {'success': False}

    try:
        context = get_label_context(request)
    except LookupError as e:
        return_dict['error'] = str(e)
        return return_dict

    if context['text'] is None:
        return_dict['error'] = 'Please provide the text for the label'
        return return_dict

    try:
        im = create_label_im(**context)
        if DEBUG:
            im.save('sample-out.png')

        # Determine rotation
        rotate = 0
        if context['kind'] == ENDLESS_LABEL:
            rotate = 0 if context['orientation'] == 'standard' else 90
        elif context['kind'] in (ROUND_DIE_CUT_LABEL, DIE_CUT_LABEL):
            rotate = 'auto'

        # Create raster data
        qlr = BrotherQLRaster(CONFIG['PRINTER']['MODEL'])
        red = 'red' in context['label_size']
        create_label(qlr, im, context['label_size'], red=red,
                    threshold=context['threshold'], cut=True, rotate=rotate)

        # Send to printer
        if not DEBUG and BACKEND_CLASS:
            try:
                be = BACKEND_CLASS(CONFIG['PRINTER']['PRINTER'])
                be.write(qlr.data)
                be.dispose()
                del be
            except Exception as e:
                return_dict['success'] = False
                return_dict['message'] = str(e)
                logger.warning(f'Printer communication failed: {e}')
                return return_dict

        return_dict['success'] = True
        if DEBUG:
            return_dict['data'] = str(qlr.data)

    except Exception as e:
        return_dict['success'] = False
        return_dict['error'] = str(e)
        logger.error(f'Label creation failed: {e}')

    return return_dict


@get('/api/printer/status')
def get_printer_status():
    """Get printer status information."""
    return_dict: Dict[str, Any] = {'online': False, 'model': CONFIG['PRINTER']['MODEL']}

    try:
        if BACKEND_CLASS:
            be = BACKEND_CLASS(CONFIG['PRINTER']['PRINTER'])
            be.dispose()
            return_dict['online'] = True
            return_dict['message'] = 'Printer is online and ready'
    except Exception as e:
        return_dict['message'] = f'Printer offline: {str(e)}'
        logger.warning(f'Printer status check failed: {e}')

    return return_dict


@post('/api/templates')
def save_template():
    """Save a label template."""
    return_dict: Dict[str, Any] = {'success': False}

    try:
        content_type = request.environ.get('CONTENT_TYPE', '')
        if 'application/json' not in content_type:
            return_dict['error'] = 'Content-Type must be application/json'
            return return_dict

        try:
            body_data = getattr(request.body, 'read', lambda: b'')()
            template_data = json.loads(body_data.decode('utf-8'))
        except json.JSONDecodeError:
            return_dict['error'] = 'Invalid JSON data'
            return return_dict

        # Create templates directory
        templates_dir = Path('templates')
        templates_dir.mkdir(exist_ok=True)

        # Save template
        template_name = template_data.get('name', 'untitled') if isinstance(template_data, dict) else 'untitled'
        filename = templates_dir / f"{template_name.replace(' ', '_').lower()}.json"

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(template_data, f, indent=2, ensure_ascii=False)

        return_dict['success'] = True
        return_dict['message'] = f'Template "{template_name}" saved successfully'

    except Exception as e:
        return_dict['success'] = False
        return_dict['error'] = str(e)
        logger.warning(f'Template save failed: {e}')

    return return_dict


@get('/api/templates')
def get_templates():
    """Get available templates."""
    return_dict: Dict[str, Any] = {'templates': []}

    try:
        templates_dir = Path('templates')
        if templates_dir.exists():
            for filepath in templates_dir.glob('*.json'):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        template_data = json.load(f)
                        return_dict['templates'].append(template_data)
                except Exception as e:
                    logger.warning(f'Failed to load template {filepath.name}: {e}')

    except Exception as e:
        logger.warning(f'Failed to read templates directory: {e}')

    return return_dict


@post('/api/preview/qr')
@get('/api/preview/qr')
def get_qr_preview():
    """Generate QR code preview."""
    if not QR_AVAILABLE:
        response.status = 500
        return {'error': 'QR code generation not available. Install qrcode package.'}

    try:
        qr_data = getattr(request.forms, 'get', lambda x, y: y)('data', '') or getattr(request.query, 'get', lambda x, y: y)('data', '')
        if not qr_data:
            response.status = 400
            return {'error': 'QR data is required'}

        qr = qrcode.QRCode(  # type: ignore
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,  # type: ignore
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white")

        return_format = getattr(request.query, 'get', lambda x, y: y)('return_format', 'png')
        if return_format == 'base64':
            import base64
            response.set_header('Content-type', 'text/plain')
            return base64.b64encode(image_to_png_bytes(qr_img))  # type: ignore
        else:
            response.set_header('Content-type', 'image/png')
            return image_to_png_bytes(qr_img)  # type: ignore
    except Exception as e:
        response.status = 500
        return {'error': f'QR code generation failed: {str(e)}'}


@route('/templates')
@view('templates.jinja2')
def templates_page():
    """Templates management page."""
    return {
        'website': CONFIG['WEBSITE'],
        'label': CONFIG['LABEL']
    }


@route('/history')
@view('history.jinja2')
def history_page():
    """Print history page."""
    return {
        'website': CONFIG['WEBSITE'],
        'label': CONFIG['LABEL']
    }


def validate_config() -> None:
    """Validate configuration and set up defaults."""
    global CONFIG

    # Ensure required sections exist
    required_sections = ['SERVER', 'PRINTER', 'LABEL', 'WEBSITE']
    for section in required_sections:
        if section not in CONFIG:
            raise ValueError(f"Missing required config section: {section}")

    # Validate label size
    if CONFIG['LABEL']['DEFAULT_SIZE'] not in label_sizes:
        raise ValueError(f"Invalid default label size: {CONFIG['LABEL']['DEFAULT_SIZE']}")


def setup_fonts(additional_font_folder: Optional[str] = None) -> None:
    """Set up font system with whitelist support."""
    global FONTS, CONFIG

    FONTS = get_whitelisted_fonts(additional_font_folder)

    if not FONTS:
        sys.stderr.write("Not a single font was found on your system. Please install some or use the \"--font-folder\" argument.\n")
        sys.exit(2)

    # Handle default font selection
    default_fonts = CONFIG['LABEL']['DEFAULT_FONTS']
    if isinstance(default_fonts, list):
        # Try each font in the list
        for font in default_fonts:
            try:
                FONTS[font['family']][font['style']]
                CONFIG['LABEL']['DEFAULT_FONTS'] = font
                logger.debug(f"Selected default font: {font}")
                break
            except KeyError:
                continue
        else:
            # No default font found, select random
            family = random.choice(list(FONTS.keys()))
            style = random.choice(list(FONTS[family].keys()))
            CONFIG['LABEL']['DEFAULT_FONTS'] = {'family': family, 'style': style}
            sys.stderr.write(f'Could not find any of the default fonts. Using: {family} ({style})\n')
    elif isinstance(default_fonts, dict):
        # Single font configuration
        try:
            FONTS[default_fonts['family']][default_fonts['style']]
        except KeyError:
            # Default font not found, select random
            family = random.choice(list(FONTS.keys()))
            style = random.choice(list(FONTS[family].keys()))
            CONFIG['LABEL']['DEFAULT_FONTS'] = {'family': family, 'style': style}
            sys.stderr.write(f'Default font not found. Using: {family} ({style})\n')


def main():
    """Main application entry point."""
    global DEBUG, BACKEND_CLASS, CONFIG

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default=False, help='Port to run server on')
    parser.add_argument('--loglevel', type=lambda x: getattr(logging, x.upper()),
                       default=False, help='Log level')
    parser.add_argument('--font-folder', default=False,
                       help='Folder for additional .ttf/.otf fonts')
    parser.add_argument('--default-label-size', default=False,
                       help='Label size inserted in your printer. Defaults to 62.')
    parser.add_argument('--default-orientation', default=False,
                       choices=('standard', 'rotated'),
                       help='Label orientation, defaults to "standard"')
    parser.add_argument('--model', default=False, choices=models,
                       help='The model of your printer (default: QL-500)')
    parser.add_argument('printer', nargs='?', default=False,
                       help='String descriptor for the printer to use')
    args = parser.parse_args()

    # Override config with command line arguments
    if args.printer:
        CONFIG['PRINTER']['PRINTER'] = args.printer
    if args.model:
        CONFIG['PRINTER']['MODEL'] = args.model
    if args.default_label_size:
        CONFIG['LABEL']['DEFAULT_SIZE'] = args.default_label_size
    if args.default_orientation:
        CONFIG['LABEL']['DEFAULT_ORIENTATION'] = args.default_orientation

    # Set up logging
    loglevel = args.loglevel or CONFIG['SERVER']['LOGLEVEL']
    if isinstance(loglevel, str):
        loglevel = getattr(logging, loglevel.upper())

    DEBUG = loglevel == logging.DEBUG
    logging.basicConfig(level=loglevel)

    # Validate configuration
    try:
        validate_config()
    except ValueError as e:
        parser.error(str(e))

    # Set up printer backend
    try:
        selected_backend = guess_backend(CONFIG['PRINTER']['PRINTER'])
    except ValueError:
        parser.error("Couldn't guess the backend to use from the printer string descriptor")

    BACKEND_CLASS = backend_factory(selected_backend)['backend_class']

    # Set up fonts
    additional_font_folder = args.font_folder or CONFIG['SERVER']['ADDITIONAL_FONT_FOLDER']
    setup_fonts(additional_font_folder)

    # Start server
    port = args.port or CONFIG['SERVER']['PORT']
    host = CONFIG['SERVER']['HOST']

    logger.info(f"Starting Brother QL Web server on {host}:{port}")
    run(host=host, port=port, debug=DEBUG)


if __name__ == '__main__':
    main()
