#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cross-platform font discovery and management for Brother QL Web.
Uses native system APIs and Python libraries instead of fontconfig.
"""

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, Optional, List, Set
import sys

logger = logging.getLogger(__name__)


def normalize_font_style(style: str) -> str:
    """
    Normalize font style names to English equivalents and handle localized names.

    Args:
        style: Original font style name (potentially localized)

    Returns:
        Normalized English style name
    """
    # Clean and normalize the input, handling special characters
    style_clean = style.strip()

    # Normalize special characters (Turkish, Vietnamese, etc.)
    char_mappings = {
        # Turkish characters
        'İ': 'I', 'ı': 'i', 'Ğ': 'G', 'ğ': 'g',
        'Ş': 'S', 'ş': 's', 'Ç': 'C', 'ç': 'c',
        'Ü': 'U', 'ü': 'u', 'Ö': 'O', 'ö': 'o',
        # Hungarian characters
        'ő': 'o', 'Ő': 'O', 'ű': 'u', 'Ű': 'U',
        'é': 'e', 'É': 'E', 'á': 'a', 'Á': 'A',
        'í': 'i', 'Í': 'I', 'ó': 'o', 'Ó': 'O',
        'ú': 'u', 'Ú': 'U',
        # Czech characters
        'ň': 'n', 'Ň': 'N', 'č': 'c', 'Č': 'C',
        'ř': 'r', 'Ř': 'R', 'š': 's', 'Š': 'S',
        'ž': 'z', 'Ž': 'Z', 'ď': 'd', 'Ď': 'D',
        'ť': 't', 'Ť': 'T', 'ě': 'e', 'Ě': 'E',
        'ů': 'u', 'Ů': 'U',
        # Vietnamese characters
        'ạ': 'a', 'Ạ': 'A', 'ậ': 'a', 'Ậ': 'A',
        'ẩ': 'a', 'Ẩ': 'A', 'ầ': 'a', 'ấ': 'a',
        'â': 'a', 'ă': 'a', 'đ': 'd', 'Đ': 'D',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ệ': 'e',
        'ễ': 'e', 'ể': 'e', 'ì': 'i', 'í': 'i',
        'ị': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ò': 'o',
        'ó': 'o', 'ọ': 'o', 'ỏ': 'o', 'õ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ộ': 'o',
        'ổ': 'o', 'ỗ': 'o', 'ơ': 'o', 'ờ': 'o',
        'ớ': 'o', 'ợ': 'o', 'ở': 'o', 'ỡ': 'o',
        'ù': 'u', 'ú': 'u', 'ụ': 'u', 'ủ': 'u',
        'ũ': 'u', 'ư': 'u', 'ừ': 'u', 'ứ': 'u',
        'ự': 'u', 'ử': 'u', 'ữ': 'u', 'ỳ': 'y',
        'ý': 'y', 'ỵ': 'y', 'ỷ': 'y', 'ỹ': 'y',
    }

    # Apply character normalization
    for char, replacement in char_mappings.items():
        style_clean = style_clean.replace(char, replacement)

    style_lower = style_clean.lower()

    # Comprehensive style mappings from various languages to English
    style_mappings = {
        # Regular/Normal variants
        'regular': 'Regular', 'normal': 'Regular', 'book': 'Regular',
        'roman': 'Regular', 'standard': 'Regular', 'standaard': 'Regular',
        'normaali': 'Regular', 'normalny': 'Regular', 'normal': 'Regular',
        'normalne': 'Regular', 'obycejne': 'Regular', 'navadno': 'Regular',
        'normale': 'Regular', 'thuong': 'Regular', 'arrunta': 'Regular',

        # Bold variants
        'bold': 'Bold', 'fett': 'Bold', 'fed': 'Bold', 'fet': 'Bold',
        'gras': 'Bold', 'grassetto': 'Bold', 'negreta': 'Bold',
        'negrito': 'Bold', 'vet': 'Bold', 'lihavoitu': 'Bold',
        'lodia': 'Bold', 'pogrubiony': 'Bold', 'felkover': 'Bold',
        'tucne': 'Bold', 'tucna': 'Bold', 'krepko': 'Bold',
        'halvfet': 'Bold', 'kalin': 'Bold', 'dam': 'Bold',
        'negrita': 'Bold', 'pogrubiona': 'Bold',

        # Italic variants
        'italic': 'Italic', 'italique': 'Italic', 'corsivo': 'Italic',
        'kursiv': 'Italic', 'cursief': 'Italic', 'kursivoitu': 'Italic',
        'kursywa': 'Italic', 'dolt': 'Italic', 'kurziva': 'Italic',
        'posevno': 'Italic', 'etzana': 'Italic', 'nghieng': 'Italic',
        'italik': 'Italic', 'cursiva': 'Italic', 'italico': 'Italic',

        # Bold Italic combinations
        'bold italic': 'Bold Italic', 'fett kursiv': 'Bold Italic',
        'fed kursiv': 'Bold Italic', 'fet italic': 'Bold Italic',
        'gras italique': 'Bold Italic', 'grassetto corsivo': 'Bold Italic',
        'negreta italic': 'Bold Italic', 'negrito italic': 'Bold Italic',
        'vet cursief': 'Bold Italic', 'lihavoitu kursivoi': 'Bold Italic',
        'lodi etzana': 'Bold Italic', 'pogrubiona kursywa': 'Bold Italic',
        'felkover dolt': 'Bold Italic', 'tucna kurziva': 'Bold Italic',
        'tucne kurziva': 'Bold Italic', 'krepko posevno': 'Bold Italic',
        'halvfet italic': 'Bold Italic', 'kalin italik': 'Bold Italic',
        'nghieng dam': 'Bold Italic', 'negrita cursiva': 'Bold Italic',
        'bold cursiva': 'Bold Italic', 'bold italico': 'Bold Italic',
        'italic dam': 'Bold Italic',

        # Light variants
        'light': 'Light', 'leger': 'Light', 'leggero': 'Light',
        'licht': 'Light', 'thin': 'Thin', 'ultralight': 'UltraLight',

        # Medium/Semibold variants
        'medium': 'Medium', 'moyen': 'Medium', 'medio': 'Medium',
        'mittel': 'Medium', 'semibold': 'Semibold', 'demi-gras': 'Semibold',
        'halbfett': 'Semibold', 'demi': 'Semibold',

        # Heavy/Black variants
        'black': 'Black', 'heavy': 'Heavy', 'noir': 'Black',
        'nero': 'Black', 'schwarz': 'Black', 'ultra': 'Ultra',
        'extrabold': 'ExtraBold', 'ultrabold': 'UltraBold',

        # Width variants
        'condensed': 'Condensed', 'condense': 'Condensed', 'narrow': 'Narrow',
        'compressed': 'Compressed', 'extended': 'Extended', 'expanded': 'Expanded',
        'wide': 'Wide',
    }

    # Direct lookup for exact matches
    if style_lower in style_mappings:
        return style_mappings[style_lower]

    # Handle compound styles by mapping individual words
    words = style_lower.split()
    normalized_words = []

    for word in words:
        if word in style_mappings:
            mapped_word = style_mappings[word]
            if mapped_word not in normalized_words:
                normalized_words.append(mapped_word)
        else:
            # Pattern matching for unmapped words
            if word in ['thuong', 'regular', 'normal', 'normale', 'normaali', 'normalny', 'normalne', 'obycejne']:
                if 'Regular' not in normalized_words:
                    normalized_words.append('Regular')
            elif word in ['dam', 'bold', 'fett', 'fed', 'fet', 'gras', 'negrita', 'negrito', 'vet', 'lihavoitu', 'lodia', 'pogrubiony', 'felkover', 'tucne', 'tucna', 'krepko', 'halvfet', 'kalin']:
                if 'Bold' not in normalized_words:
                    normalized_words.append('Bold')
            elif word in ['nghieng', 'italic', 'italique', 'corsivo', 'kursiv', 'cursief', 'kursivoitu', 'kursywa', 'dolt', 'kurziva', 'posevno', 'etzana', 'italik', 'cursiva', 'italico']:
                if 'Italic' not in normalized_words:
                    normalized_words.append('Italic')
            else:
                # Keep unknown words but capitalize them properly
                cap_word = word.capitalize()
                if cap_word not in normalized_words:
                    normalized_words.append(cap_word)

    if normalized_words:
        # Sort to ensure consistent ordering (weight before style)
        result_words = []
        weight_order = ['Thin', 'UltraLight', 'Light', 'Regular', 'Medium', 'Semibold', 'Bold', 'ExtraBold', 'UltraBold', 'Black', 'Heavy', 'Ultra']
        width_order = ['Compressed', 'Condensed', 'Narrow', 'Extended', 'Expanded', 'Wide']
        style_order = ['Italic', 'Oblique']

        # Add weight words in order
        for ordered_word in weight_order:
            if ordered_word in normalized_words:
                result_words.append(ordered_word)
                break  # Only one weight

        # Add width words
        for ordered_word in width_order:
            if ordered_word in normalized_words:
                result_words.append(ordered_word)

        # Add style words
        for ordered_word in style_order:
            if ordered_word in normalized_words:
                result_words.append(ordered_word)

        # Add any remaining words
        for word in normalized_words:
            if word not in result_words:
                result_words.append(word)

        return ' '.join(result_words) if result_words else 'Regular'

    # If no mapping found, return the original style with proper capitalization
    return ' '.join(word.capitalize() for word in words) if words else style.strip()


def get_system_font_paths() -> List[Path]:
    """Get system font directories based on the current platform."""
    system = platform.system()
    font_paths = []

    if system == "Darwin":  # macOS
        font_paths = [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        ]
    elif system == "Linux":
        font_paths = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local" / "share" / "fonts",
        ]
    elif system == "Windows":
        font_paths = [
            Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
            Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
        ]

    # Filter to existing directories
    return [path for path in font_paths if path.exists() and path.is_dir()]


def parse_font_file(font_path: Path) -> Optional[Dict[str, str]]:
    """
    Parse a font file to extract family and style information.
    Uses platform-specific methods for better accuracy.
    """
    try:
        system = platform.system()

        if system == "Darwin":  # macOS
            return parse_font_macos(font_path)
        elif system == "Linux":
            # Try fontconfig first, then fallback to filename parsing
            font_info = parse_font_fontconfig(font_path)
            if font_info:
                return font_info
            return parse_font_filename(font_path)
        else:
            # Windows or other systems - use filename parsing
            return parse_font_filename(font_path)

    except Exception as e:
        logger.debug(f"Failed to parse font {font_path}: {e}")
        return None


def parse_font_macos(font_path: Path) -> Optional[Dict[str, str]]:
    """Parse font using macOS system tools."""
    # For now, use filename parsing on macOS as mdls output is complex
    # Future improvement: use PyObjC to access Core Text APIs directly
    return parse_font_filename(font_path)


def parse_font_fontconfig(font_path: Path) -> Optional[Dict[str, str]]:
    """Parse font using fontconfig (Linux)."""
    try:
        # Use fc-scan to get font information
        result = subprocess.run(
            ["fc-scan", "--format", "%{family}:%{style}\n", str(font_path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )

        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        family = parts[0].strip()
                        style = parts[1].strip()
                        if family and style:
                            # Take the first family name if multiple
                            if ',' in family:
                                family = family.split(',')[0].strip()
                            if ',' in style:
                                style = style.split(',')[0].strip()
                            return {"family": family, "style": style, "path": str(font_path)}

        return None

    except (subprocess.SubprocessError, subprocess.TimeoutExpired, FileNotFoundError):
        logger.debug(f"fc-scan not available or failed for {font_path}")
        return None


def parse_font_filename(font_path: Path) -> Optional[Dict[str, str]]:
    """Parse font information from filename as fallback."""
    try:
        # Remove extension and clean up name
        name = font_path.stem.replace('_', ' ').replace('-', ' ')

        # Handle common font file naming patterns
        # Pattern 1: FamilyName-Style (e.g., Arial-Bold, Times-BoldItalic)
        if '-' in font_path.stem:
            parts = font_path.stem.split('-', 1)
            if len(parts) == 2:
                family_part = parts[0].replace('_', ' ')
                style_part = parts[1].replace('_', ' ')

                # Clean and normalize the style
                normalized_style = normalize_font_style(style_part)
                if normalized_style and normalized_style != style_part:
                    return {"family": family_part, "style": normalized_style, "path": str(font_path)}

        # Pattern 2: Family Name with style words mixed in
        name_words = name.split()
        style_words = []
        family_words = []

        # Common style indicators (order matters for compound styles)
        style_indicators = [
            ('bolditalic', 'Bold Italic'), ('boldobl', 'Bold Oblique'),
            ('italic', 'Italic'), ('oblique', 'Oblique'),
            ('bold', 'Bold'), ('light', 'Light'), ('thin', 'Thin'),
            ('medium', 'Medium'), ('regular', 'Regular'), ('normal', 'Regular'),
            ('black', 'Black'), ('heavy', 'Heavy'),
            ('condensed', 'Condensed'), ('extended', 'Extended'),
            ('narrow', 'Narrow'), ('wide', 'Wide')
        ]

        name_lower = name.lower().replace(' ', '')

        # Check for compound style first
        for indicator, style in style_indicators:
            if indicator in name_lower:
                style_words.append(style)
                name_lower = name_lower.replace(indicator, '')
                break

        # Extract family name (what's left after removing style)
        if style_words:
            # Remove style indicators from original name
            family_name = name
            for indicator, _ in style_indicators:
                family_name = family_name.replace(indicator.title(), ' ')
                family_name = family_name.replace(indicator.upper(), ' ')
                family_name = family_name.replace(indicator.lower(), ' ')
            family_name = ' '.join(family_name.split())  # Clean up spaces
        else:
            family_name = name
            style_words = ['Regular']

        # Clean up family name
        family_name = family_name.strip(' -_')
        if not family_name:
            family_name = font_path.stem

        style = ' '.join(style_words) if style_words else 'Regular'

        return {"family": family_name, "style": style, "path": str(font_path)}

    except Exception as e:
        logger.debug(f"Filename parsing failed for {font_path}: {e}")
        return None


def split_font_name(font_name: str) -> tuple[str, str]:
    """Split a full font name into family and style."""
    # Clean the font name
    clean_name = font_name.strip()

    # Common style suffixes (longest first to match compound styles)
    style_suffixes = [
        'Bold Italic', 'Bold Oblique', 'Light Italic', 'Medium Italic',
        'BoldItalic', 'BoldOblique', 'LightItalic', 'MediumItalic',
        'ExtraBold', 'UltraBold', 'SemiBold', 'UltraLight',
        'Bold', 'Italic', 'Oblique', 'Light', 'Thin', 'Medium',
        'Black', 'Heavy', 'Regular', 'Normal', 'Condensed', 'Extended'
    ]

    # Try to find style suffix
    for suffix in style_suffixes:
        # Check exact match at end
        if clean_name.endswith(' ' + suffix):
            family = clean_name[:-len(suffix)-1].strip()
            return family, suffix
        elif clean_name.endswith('-' + suffix):
            family = clean_name[:-len(suffix)-1].strip()
            return family, suffix
        elif clean_name == suffix:
            return suffix, 'Regular'

    # If no style found, assume it's all family name
    return clean_name, 'Regular'


def scan_font_directory(directory: Path) -> Dict[str, Dict[str, str]]:
    """Scan a directory for font files and extract font information."""
    fonts = {}

    if not directory.exists() or not directory.is_dir():
        return fonts

    # Supported font extensions
    font_extensions = {'.ttf', '.otf', '.ttc', '.dfont'}

    try:
        font_count = 0
        # Walk through directory recursively
        for font_file in directory.rglob('*'):
            if font_file.is_file() and font_file.suffix.lower() in font_extensions:
                font_info = parse_font_file(font_file)

                if font_info and font_info.get('family') and font_info.get('style'):
                    family = font_info['family'].strip()
                    style = normalize_font_style(font_info['style'])
                    path = font_info['path']

                    # Skip empty or invalid family names
                    if not family or len(family) < 2:
                        continue

                    # Skip system/hidden fonts that start with dots
                    if family.startswith('.'):
                        continue

                    if family not in fonts:
                        fonts[family] = {}

                    # Only add if we don't already have this style
                    if style not in fonts[family]:
                        fonts[family][style] = path
                        logger.debug(f"Added font: {family} ({style}) -> {font_file.name}")
                        font_count += 1
                    else:
                        logger.debug(f"Skipped duplicate: {family} ({style})")

        logger.debug(f"Scanned {directory}: found {font_count} fonts in {len(fonts)} families")

    except Exception as e:
        logger.warning(f"Error scanning directory {directory}: {e}")

    return fonts


def get_fonts(folder: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """
    Scan for fonts using cross-platform methods.

    Args:
        folder: Optional path to scan for fonts. If None, scans system fonts.

    Returns:
        Dictionary mapping font family names to style dictionaries,
        which map style names to font file paths.
    """
    fonts = {}

    if folder:
        # Scan specific folder
        folder_path = Path(folder)
        if folder_path.exists():
            fonts.update(scan_font_directory(folder_path))
        else:
            logger.warning(f"Font folder does not exist: {folder}")
    else:
        # Scan system font directories
        system_paths = get_system_font_paths()
        logger.info(f"Scanning system font directories: {[str(p) for p in system_paths]}")

        for path in system_paths:
            try:
                logger.debug(f"Scanning {path}")
                path_fonts = scan_font_directory(path)

                # Merge fonts, avoiding duplicates
                for family, styles in path_fonts.items():
                    if family not in fonts:
                        fonts[family] = {}
                    for style, font_path in styles.items():
                        if style not in fonts[family]:
                            fonts[family][style] = font_path

            except Exception as e:
                logger.warning(f"Error scanning {path}: {e}")

    logger.info(f"Loaded {len(fonts)} font families with {sum(len(styles) for styles in fonts.values())} total styles")
    return fonts


def validate_font_path(font_path: str) -> bool:
    """
    Validate that a font file exists and is readable.

    Args:
        font_path: Path to the font file

    Returns:
        True if the font file is valid, False otherwise
    """
    try:
        path = Path(font_path)
        if not path.exists() or not path.is_file():
            return False

        # Check if it's a supported font file
        supported_extensions = {'.ttf', '.otf', '.ttc', '.dfont'}
        return path.suffix.lower() in supported_extensions

    except Exception as e:
        logger.debug(f"Font validation failed for {font_path}: {e}")
        return False


def get_font_families(fonts: Dict[str, Dict[str, str]]) -> List[str]:
    """
    Get a sorted list of font family names.

    Args:
        fonts: Font dictionary from get_fonts()

    Returns:
        Sorted list of font family names
    """
    return sorted(fonts.keys())


def get_font_styles(fonts: Dict[str, Dict[str, str]], family: str) -> List[str]:
    """
    Get available styles for a font family.

    Args:
        fonts: Font dictionary from get_fonts()
        family: Font family name

    Returns:
        List of available styles for the family
    """
    return list(fonts.get(family, {}).keys())


def find_font_path(fonts: Dict[str, Dict[str, str]], family: str, style: str) -> Optional[str]:
    """
    Find the file path for a specific font family and style.

    Args:
        fonts: Font dictionary from get_fonts()
        family: Font family name
        style: Font style name

    Returns:
        Font file path if found, None otherwise
    """
    try:
        return fonts[family][style]
    except KeyError:
        return None
