import logging
import os
import socket
import time
import winreg
from typing import List, Optional
import psutil

from ..models.network import NetworkSummaryModel
from ..models.metadata import CollectionMetadataModel, WarningItem
from .subprocess_helper import safe_run_command

logger = logging.getLogger("windows-diagnostics.services.network")

class NetworkService:
    """
    Service for querying local IP configurations, DNS, gateway, and internet status.
    """

    def _get_local_ips(self) -> List[str]:
        """
        Retrieves all non-loopback IPv4 addresses assigned to network interfaces.
        """
        ips = []
        try:
            interfaces = psutil.net_if_addrs()
            for interface_name, addresses in interfaces.items():
                for addr in addresses:
                    # Filter for IPv4 and skip loopback
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        ips.append(addr.address)
        except Exception as e:
            logger.warning(f"Error querying network interface addresses: {e}")
            try:
                hostname = socket.gethostname()
                ips.append(socket.gethostbyname(hostname))
            except Exception:
                pass
        return ips

    def _get_default_gateway(self) -> Optional[str]:
        """
        Retrieves the default gateway IP on Windows by parsing the active 0.0.0.0 route.
        """
        try:
            code, stdout, stderr = safe_run_command(["route", "print", "0.0.0.0"], timeout=2.0)
            if code == 0:
                for line in stdout.splitlines():
                    parts = line.split()
                    # A route entry usually lists: Destination Netmask Gateway Interface Metric
                    if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                        return parts[2]
        except Exception as e:
            logger.debug(f"Error querying default gateway via route command: {e}")
        return None

    def _get_dns_servers(self) -> List[str]:
        """
        Queries DNS server IP addresses from registry.
        """
        dns_servers = []
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
            ) as key:
                try:
                    ns, _ = winreg.QueryValueEx(key, "NameServer")
                    if ns:
                        dns_servers.extend([x.strip() for x in ns.split(",") if x.strip()])
                except FileNotFoundError:
                    pass

                try:
                    dhcp_ns, _ = winreg.QueryValueEx(key, "DhcpNameServer")
                    if dhcp_ns:
                        dns_servers.extend([x.strip() for x in dhcp_ns.split() if x.strip()])
                except FileNotFoundError:
                    pass
        except Exception as e:
            logger.debug(f"Error reading root Tcpip parameters registry: {e}")

        # Check adapter specific interfaces if root DNS is not found
        if not dns_servers:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
                ) as interfaces_key:
                    info = winreg.QueryInfoKey(interfaces_key)
                    for i in range(info[0]):
                        subkey_name = winreg.EnumKey(interfaces_key, i)
                        with winreg.OpenKey(interfaces_key, subkey_name) as subkey:
                            for val_name in ["NameServer", "DhcpNameServer"]:
                                try:
                                    val, _ = winreg.QueryValueEx(subkey, val_name)
                                    if val:
                                        dns_servers.extend(
                                            [x.strip() for x in val.replace(",", " ").split() if x.strip()]
                                        )
                                except FileNotFoundError:
                                    pass
            except Exception as e:
                logger.debug(f"Error reading adapter Interfaces registry: {e}")

        # Deduplicate results
        seen = set()
        return [x for x in dns_servers if not (x in seen or seen.add(x))]

    def _check_internet_connection(self) -> tuple[str, bool]:
        """
        Performs a multi-target reachability probe using sockets to prevent VPN/firewall false negatives.
        Returns:
            Tuple[reachability_status, connected_flag]
            Reachability status: "success" | "failed" | "timeout" | "unknown"
        """
        targets = [
            ("8.8.8.8", 53),                 # Google DNS
            ("1.1.1.1", 53),                 # Cloudflare DNS
            ("clients3.google.com", 80),     # Google connectivity check
            ("www.msftconnecttest.com", 80)  # Microsoft connectivity check
        ]

        has_timeout = False
        has_error = False

        for host, port in targets:
            try:
                # 1.0s timeout per target to prevent blocking the MCP tool
                with socket.create_connection((host, port), timeout=1.0) as s:
                    return "success", True
            except socket.timeout:
                has_timeout = True
            except Exception:
                has_error = True

        if has_timeout:
            return "timeout", False
        if has_error:
            return "failed", False
        return "unknown", False

    def get_network_summary(self) -> NetworkSummaryModel:
        """
        Compiles the network summary metrics.
        """
        start_time = time.perf_counter()
        warnings = []
        status = "ok"

        # Check network interfaces available
        net_interface_available = False
        try:
            stats = psutil.net_if_stats()
            # If any non-loopback interface is UP
            for name, item in stats.items():
                if item.isup and "loopback" not in name.lower():
                    net_interface_available = True
                    break
        except Exception as e:
            logger.warning(f"Error reading network interface statistics: {e}")
            warnings.append(WarningItem(component="network", code="INTERFACE_STATS_FAILED", message=str(e)))
            status = "partial"

        # Check local IPs
        local_ips = self._get_local_ips()
        local_network_available = len(local_ips) > 0

        # Gateway & DNS
        gateway = self._get_default_gateway()
        dns = self._get_dns_servers()

        # Outbound Reachability Check
        reachability_status, connected = self._check_internet_connection()
        if reachability_status in ["timeout", "failed"]:
            warnings.append(
                WarningItem(
                    component="network",
                    code="OUTBOUND_PROBE_FAILED",
                    message=f"Outbound network check returned status: {reachability_status}"
                )
            )
            # Do not declare a full query error for standard offline state
            if reachability_status == "timeout":
                status = "partial"

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings
        )

        return NetworkSummaryModel(
            hostname=socket.gethostname(),
            local_ips=local_ips,
            default_gateway=gateway,
            dns_servers=dns,
            network_interface_available=net_interface_available,
            local_network_available=local_network_available,
            internet_reachability_check=reachability_status,
            internet_connected=connected,
            collection_metadata=metadata
        )
