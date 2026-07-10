def flag_emoji(country_code):
    """Convert an ISO 3166-1 alpha-2 code (e.g. 'IT') into a flag emoji."""
    if not country_code or len(country_code) != 2:
        return "🌐"
    code = country_code.upper()
    if not code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)
