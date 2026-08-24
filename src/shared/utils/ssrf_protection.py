import ipaddress
import socket
from urllib.parse import urlparse
from src.shared.utils.logger import Log

def is_safe_url(url: str) -> bool:
    """
    Validate if a URL is safe from SSRF attacks.
    Checks:
    - Proper HTTP/HTTPS scheme.
    - Hostname exists.
    - Resolves hostname to IPs and ensures none are private, loopback, link-local, or reserved.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            Log.warning(f"[SSRF Protection] Rejected scheme: {parsed.scheme}")
            return False
        
        hostname = parsed.hostname
        if not hostname:
            Log.warning("[SSRF Protection] Missing hostname")
            return False
        
        # Check basic local/private strings to save DNS calls
        hostname_lower = hostname.lower()
        if hostname_lower in ('localhost', 'localhost.localdomain', '127.0.0.1', '::1'):
            Log.warning(f"[SSRF Protection] Blocked local hostname: {hostname}")
            return False

        # Resolve DNS to check IP addresses
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            Log.warning(f"[SSRF Protection] DNS resolution failed for {hostname}: {e}")
            return False

        for info in addr_info:
            ip_str = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
                # Check for loopback, private, link-local, unspecified, or reserved IPs
                if (ip.is_loopback or 
                    ip.is_private or 
                    ip.is_link_local or 
                    ip.is_unspecified or 
                    ip.is_reserved):
                    Log.warning(f"[SSRF Protection] Blocked unsafe/private IP address: {ip_str} for host: {hostname}")
                    return False
            except ValueError:
                # If it's not a valid IP (should not happen after getaddrinfo, but to be safe)
                Log.warning(f"[SSRF Protection] Invalid IP format resolved: {ip_str}")
                return False

        return True
    except Exception as e:
        Log.error(f"[SSRF Protection] Error validating URL {url}: {e}")
        return False
