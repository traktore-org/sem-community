# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.2.x   | Yes       |
| < 1.2   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in SEM, please report it responsibly:

1. **Do NOT open a public issue**
2. Email the maintainer or use [GitHub Security Advisories](https://github.com/traktore-org/sem-community/security/advisories/new)
3. Include: description, steps to reproduce, potential impact

We will respond within 48 hours and work on a fix before any public disclosure.

## Security Considerations

SEM runs locally inside Home Assistant — no cloud, no external API calls. However:

- **Observer mode**: When enabled, SEM never sends commands to hardware. Use this on test instances.
- **Service calls**: SEM controls EV chargers and battery inverters via HA services. Ensure your HA instance is properly secured.
- **Legionella prevention**: The forced heating cycle cannot be disabled — this is a safety feature, not a bug.
- **No credentials stored**: SEM uses HA's built-in integrations for hardware access. It does not store API keys or passwords.
