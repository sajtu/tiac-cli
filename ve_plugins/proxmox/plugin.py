"""Proxmox VE support plugin for tiac-cli."""

from __future__ import annotations

import json
import socket
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PLUGIN_ID = "proxmox"

OSTYPE_DISPLAY = {
    "l24": "Linux 2.4 Kernel",
    "l26": "Linux",
    "solaris": "Solaris",
    "other": "Other",
    "wxp": "Windows XP",
    "w2k": "Windows 2000",
    "w2k3": "Windows Server 2003",
    "w2k8": "Windows Server 2008",
    "wvista": "Windows Vista",
    "win7": "Windows 7",
    "win8": "Windows 8/8.1",
    "win10": "Windows 10/2016/2019",
    "win11": "Windows 11/2022/2025",
}


def os_display(ostype: str) -> str:
    return OSTYPE_DISPLAY.get(ostype, ostype or "Unknown")


class PluginError(RuntimeError):
    pass


def metadata(plugin_dir: Path) -> dict[str, Any]:
    with (plugin_dir / "plugin.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def endpoint_url(ve: dict[str, Any]) -> str:
    return f"https://{ve['host']}:{int(ve['port'])}/api2/json"


def authorization_header(credentials: dict[str, str]) -> str:
    token_id = credentials.get("token_id", "").strip()
    token_secret = credentials.get("token_secret", "").strip()
    if not token_id or not token_secret:
        raise PluginError("Both Proxmox token ID and token secret are required")
    return f"PVEAPIToken={token_id}={token_secret}"


def _ssl_context(verify_tls: bool) -> ssl.SSLContext:
    if verify_tls:
        return ssl.create_default_context()
    return ssl._create_unverified_context()  # noqa: SLF001


def api_get(
    ve: dict[str, Any],
    credentials: dict[str, str],
    path: str,
    query: dict[str, str] | None = None,
    timeout: int = 10,
) -> Any:
    suffix = path if path.startswith("/") else f"/{path}"
    url = endpoint_url(ve) + suffix
    if query:
        url += "?" + urllib.parse.urlencode(query)

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": authorization_header(credentials),
            "Accept": "application/json",
            "User-Agent": "tiac-cli/0.3.1.0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=_ssl_context(bool(ve.get("verify_tls", True))),
        ) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.reason
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = body.get("errors") or body.get("message") or detail
        except Exception:
            pass
        raise PluginError(f"Proxmox API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise PluginError(f"Unable to connect to Proxmox API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise PluginError("Proxmox API connection timed out") from exc

    if not isinstance(payload, dict) or "data" not in payload:
        raise PluginError("Endpoint did not return a valid Proxmox API response")
    return payload["data"]


def resolve_and_connect(host: str, port: int, timeout: int = 5) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PluginError(f"Hostname does not resolve: {host}: {exc}") from exc

    addresses: list[str] = []
    last_error: OSError | None = None
    for family, socktype, proto, _, sockaddr in infos:
        address = sockaddr[0]
        if address not in addresses:
            addresses.append(address)
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return addresses
        except OSError as exc:
            last_error = exc
        finally:
            sock.close()
    raise PluginError(
        f"Unable to connect to {host}:{port}: {last_error or 'connection failed'}"
    )


def verify(
    ve: dict[str, Any], credentials: dict[str, str]
) -> dict[str, Any]:
    addresses = resolve_and_connect(ve["host"], int(ve["port"]))
    version = api_get(ve, credentials, "/version")
    nodes = api_get(ve, credentials, "/nodes")
    resources = api_get(ve, credentials, "/cluster/resources", {"type": "vm"})
    if not isinstance(version, dict) or "version" not in version:
        raise PluginError("API endpoint did not identify itself as Proxmox VE")
    if not isinstance(nodes, list):
        raise PluginError("Unable to retrieve Proxmox node list")
    if not isinstance(resources, list):
        raise PluginError("Unable to retrieve Proxmox VM/container list")
    return {
        "addresses": addresses,
        "version": version,
        "nodes": nodes,
        "resources": resources,
    }


def list_nodes(
    ve: dict[str, Any], credentials: dict[str, str]
) -> list[dict[str, Any]]:
    data = api_get(ve, credentials, "/nodes")
    return sorted(data, key=lambda item: str(item.get("node", "")))


def list_vm_resources(
    ve: dict[str, Any], credentials: dict[str, str]
) -> list[dict[str, Any]]:
    data = api_get(ve, credentials, "/cluster/resources", {"type": "vm"})
    return sorted(data, key=lambda item: int(item.get("vmid", 0)))


def list_templates(
    ve: dict[str, Any], credentials: dict[str, str]
) -> list[dict[str, Any]]:
    return [
        item
        for item in list_vm_resources(ve, credentials)
        if int(item.get("template", 0)) == 1 and item.get("type") == "qemu"
    ]


def list_used_ids(
    ve: dict[str, Any], credentials: dict[str, str]
) -> set[int]:
    return {
        int(item["vmid"])
        for item in list_vm_resources(ve, credentials)
        if "vmid" in item
    }


def list_storages(
    ve: dict[str, Any],
    credentials: dict[str, str],
    node_name: str,
) -> list[dict[str, Any]]:
    data = api_get(
        ve,
        credentials,
        f"/nodes/{urllib.parse.quote(node_name)}/storage",
        {"content": "images"},
    )
    return sorted(data, key=lambda item: str(item.get("storage", "")))


def list_all_storages(
    ve: dict[str, Any],
    credentials: dict[str, str],
    node_name: str,
) -> list[dict[str, Any]]:
    data = api_get(
        ve,
        credentials,
        f"/nodes/{urllib.parse.quote(node_name)}/storage",
    )
    return sorted(data, key=lambda item: str(item.get("storage", "")))


_TEMPLATE_DISK_RE = re.compile(
    r"^(?:(?:ide|sata|scsi|virtio)\d+|efidisk0|tpmstate0)$"
)
_VOLUME_STORAGE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):")


def _template_storage_ids(config: dict[str, Any]) -> set[str]:
    """Return every Proxmox storage ID backing an attached template disk."""
    storage_ids: set[str] = set()

    for key, raw_value in config.items():
        if not _TEMPLATE_DISK_RE.fullmatch(str(key)):
            continue

        value = str(raw_value).strip()
        if not value:
            continue

        volume = value.split(",", 1)[0].strip()
        if volume == "none":
            continue

        match = _VOLUME_STORAGE_RE.match(volume)
        if match is None:
            raise PluginError(
                f"Unable to determine storage for template disk {key}: {value}"
            )
        storage_ids.add(match.group(1))

    return storage_ids


def _storage_is_shared(storage: dict[str, Any]) -> bool:
    value = storage.get("shared", 0)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "yes", "true", "on"}


def _storage_is_available(storage: dict[str, Any]) -> bool:
    for field in ("enabled", "active"):
        value = storage.get(field, 1)
        if isinstance(value, bool):
            available = value
        elif isinstance(value, (int, float)):
            available = value != 0
        else:
            available = str(value).strip().lower() in {"1", "yes", "true", "on"}
        if not available:
            return False
    return True


def valid_clone_nodes(
    ve: dict[str, Any],
    credentials: dict[str, str],
    live_template: dict[str, Any],
    online_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Return online nodes proven able to access all template disk storage.

    Any non-shared template storage restricts cloning to the template's
    current node. Templates backed entirely by shared storage may be cloned
    only to online nodes where every required storage is active.
    """
    source_node = str(live_template.get("node", "")).strip()
    if not source_node:
        raise PluginError("Unable to determine the Proxmox Template source Node.")

    source_vmid = int(live_template["vmid"])
    config = get_qemu_config(ve, credentials, source_node, source_vmid)
    storage_ids = _template_storage_ids(config)

    # A diskless template has no storage-based node restriction.
    if not storage_ids:
        return online_nodes

    source_storages = {
        str(item.get("storage", "")): item
        for item in list_all_storages(ve, credentials, source_node)
    }
    unknown = sorted(storage_ids - source_storages.keys())
    if unknown:
        raise PluginError(
            "Unable to verify template storage availability: "
            + ", ".join(unknown)
        )
    unavailable = sorted(
        storage_id
        for storage_id in storage_ids
        if not _storage_is_available(source_storages[storage_id])
    )
    if unavailable:
        raise PluginError(
            "Template storage is not active on its source Node: "
            + ", ".join(unavailable)
        )

    non_shared = sorted(
        storage_id
        for storage_id in storage_ids
        if not _storage_is_shared(source_storages[storage_id])
    )
    if non_shared:
        matches = [
            node
            for node in online_nodes
            if str(node.get("node", "")) == source_node
        ]
        if not matches:
            raise PluginError(
                f"Template VMID {source_vmid} uses local storage "
                f"({', '.join(non_shared)}), but source Node {source_node} "
                "is not online."
            )
        return matches

    valid: list[dict[str, Any]] = []
    for node in online_nodes:
        node_name = str(node.get("node", ""))
        available = {
            str(item.get("storage", ""))
            for item in list_all_storages(ve, credentials, node_name)
            if _storage_is_available(item)
        }
        if storage_ids <= available:
            valid.append(node)

    if not valid:
        raise PluginError(
            f"No online Proxmox Node can access all storage required by "
            f"Template VMID {source_vmid}: {', '.join(sorted(storage_ids))}"
        )
    return valid


def credential_prompt_names() -> tuple[str, str]:
    return ("Proxmox API token ID", "Proxmox API token secret")


def _prompt(label: str, default: str | int | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return str(default)
        print("A value is required.")


def _prompt_bool(label: str, default: bool = True) -> bool:
    raw = _prompt(label, "yes" if default else "no").lower()
    if raw in {"yes", "y", "true", "1", "on"}:
        return True
    if raw in {"no", "n", "false", "0", "off"}:
        return False
    raise PluginError(f"{label} must be yes or no")


def _choose(title: str, items: list[tuple[str, str]]) -> str:
    if not items:
        raise PluginError(f"No choices available for {title}")
    if len(items) == 1:
        print(f"{title}: {items[0][1]}")
        return items[0][0]
    print(title)
    for index, (_, display) in enumerate(items, 1):
        print(f"  {index}) {display}")
    print("  Q) Quit/Cancel")
    while True:
        raw = input("Select: ").strip()
        if raw.lower() == "q":
            raise PluginError("Cancelled")
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return items[int(raw)-1][0]
        print("Invalid selection.")


def wizard_add_ve(*, veid: int) -> dict[str, Any]:
    name = _prompt("VE label")
    host = _prompt("Proxmox management host or FQDN")
    port = int(_prompt("Proxmox API port", 8006))
    if not 1 <= port <= 65535:
        raise PluginError("API port must be between 1 and 65535")
    verify_tls = _prompt_bool("Verify TLS certificate", True)

    # Match terminology shown in the Proxmox UI.
    username = _prompt("User name (include realm, e.g. user@pve)")
    if "@" not in username:
        raise PluginError("User name must include a Proxmox realm, e.g. user@pve")
    token_name = _prompt("Token Name")
    token_secret = _prompt("Token Secret")

    credentials = {
        "username": username,
        "token_name": token_name,
        "token_id": f"{username}!{token_name}",
        "token_secret": token_secret,
    }
    ve = {
        "id": f"{veid:04d}",
        "type": PLUGIN_ID,
        "name": name,
        "host": host,
        "port": port,
        "verify_tls": verify_tls,
    }
    print("Verifying host name, Proxmox API endpoint, and credentials...")
    verification = verify(ve, credentials)
    return {"ve": ve, "credentials": credentials, "verification": verification}

def get_vm_resource(ve: dict[str, Any], credentials: dict[str, str], vmid: int) -> dict[str, Any] | None:
    for item in list_vm_resources(ve, credentials):
        if int(item.get("vmid", -1)) == int(vmid):
            return item
    return None


def get_qemu_config(ve: dict[str, Any], credentials: dict[str, str], node: str, vmid: int) -> dict[str, Any]:
    return api_get(ve, credentials, f"/nodes/{urllib.parse.quote(node)}/qemu/{int(vmid)}/config")


def _live_template_info(
    ve: dict[str, Any], credentials: dict[str, str], vmid: int
) -> dict[str, Any]:
    resource = get_vm_resource(ve, credentials, vmid)
    if resource is None:
        return {"status": "MISSING", "vmid": vmid}
    if resource.get("type") != "qemu":
        return {"status": "WRONG-TYPE", "vmid": vmid, "resource": resource}

    node = str(resource.get("node", ""))
    config = get_qemu_config(ve, credentials, node, vmid)
    ostype = str(config.get("ostype", "") or "")
    return {
        "status": "OK" if int(resource.get("template", 0)) == 1 else "NOT-TEMPLATE",
        "vmid": vmid,
        "name": str(resource.get("name", f"vmid-{vmid}")),
        "node": node,
        "os_type": ostype,
        "os_display": os_display(ostype),
        "object_type": "qemu",
        "template": int(resource.get("template", 0)) == 1,
    }


def compare_template_cache(
    template: dict[str, Any], live: dict[str, Any]
) -> tuple[str, list[tuple[str, str, str]]]:
    if live.get("status") != "OK":
        return str(live.get("status", "ERROR")), []

    changes: list[tuple[str, str, str]] = []
    fields = (
        ("source_name", "name", "Name"),
        ("source_node_name", "node", "Node"),
        ("os_type", "os_type", "OS Type"),
        ("object_type", "object_type", "Object Type"),
    )
    for cached_key, live_key, label in fields:
        cached = str(template.get(cached_key, ""))
        current = str(live.get(live_key, ""))
        if cached != current:
            changes.append((label, cached, current))

    if any(label in {"OS Type", "Object Type"} for label, _, _ in changes):
        return "CRITICAL", changes
    if changes:
        return "CHANGED", changes
    return "OK", []


def get_live_template_status(
    ve: dict[str, Any], credentials: dict[str, str], template: dict[str, Any]
) -> tuple[dict[str, Any], str, list[tuple[str, str, str]]]:
    live = _live_template_info(ve, credentials, int(template["source_vm_id"]))
    status, changes = compare_template_cache(template, live)
    return live, status, changes


def wizard_add_template(*, ve: dict[str, Any], credentials: dict[str, str]) -> dict[str, Any]:
    print(f"Checking connection to {ve['name']} ({ve['host']}:{ve['port']})...")
    verify(ve, credentials)
    print("Connection and credentials verified.")

    while True:
        vmid = int(_prompt("Template VMID"))
        live = _live_template_info(ve, credentials, vmid)
        if live["status"] == "MISSING":
            print(f"Cannot find VMID {vmid} at {ve['host']}.")
            continue
        if live["status"] == "WRONG-TYPE":
            print(f"VMID {vmid} exists, but it is not a QEMU VM/template.")
            continue
        if live["status"] == "NOT-TEMPLATE":
            print(f"VMID {vmid} exists, but it is not marked as a Proxmox QEMU template.")
            continue
        break

    print("Validated Proxmox template:")
    print(f"  VMID: {vmid}")
    print(f"  Name: {live['name']}")
    print(f"  Node: {live['node']}")
    print(f"  OS Type: {live['os_display']} ({live['os_type']})")

    secondary_label = _prompt("Secondary label or notes", "")
    return {
        "type": "pve",
        "label": live["name"],
        "secondary_label": secondary_label,
        "ve_id": str(ve["id"]).zfill(4),
        "source_vm_id": vmid,
        "source_node_name": live["node"],
        "source_name": live["name"],
        "os_type": live["os_type"],
        "os_display": live["os_display"],
        "object_type": live["object_type"],
    }


def validate_template(
    ve: dict[str, Any], credentials: dict[str, str], template: dict[str, Any]
) -> dict[str, Any]:
    verify(ve, credentials)
    live, status, changes = get_live_template_status(ve, credentials, template)
    if status in {"MISSING", "WRONG-TYPE", "NOT-TEMPLATE", "CRITICAL"}:
        details = "; ".join(
            f"{label}: {old or '(blank)'} -> {new or '(blank)'}"
            for label, old, new in changes
        )
        raise PluginError(
            f"Template VMID {template['source_vm_id']} failed validation: {status}"
            + (f" ({details})" if details else "")
        )
    return live

def wizard_add_vm(*, ve: dict[str, Any], credentials: dict[str, str], template: dict[str, Any], inventory_id: int, prefix: str) -> dict[str, Any]:
    print(f"Checking connection to {ve['name']} ({ve['host']}:{ve['port']})...")
    verify(ve, credentials)
    print(f"Revalidating Proxmox Template VMID {template['source_vm_id']}...")
    live_template = validate_template(ve, credentials, template)
    print("Template is valid.")

    suffix = _prompt("VM name")
    clean_prefix = prefix.strip().strip("-_").lower()
    clean_suffix = suffix.strip().strip("-_").lower()
    name = f"{clean_prefix}-{clean_suffix}" if clean_prefix else clean_suffix
    if not re.fullmatch(r"(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", name):
        raise PluginError(f"Generated Proxmox VM name {name!r} is invalid.")

    nodes = [n for n in list_nodes(ve, credentials) if n.get("status") == "online"]
    if not nodes:
        raise PluginError("No online Proxmox Nodes are available.")
    nodes = valid_clone_nodes(ve, credentials, live_template, nodes)
    node_choices = [
        (str(n["node"]), f"{n['node']} ({n.get('status','unknown')})")
        for n in nodes
    ]
    if len(node_choices) == 1:
        target_node = node_choices[0][0]
        print(f"Proxmox target Node: {node_choices[0][1]} (automatically selected)")
    else:
        target_node = _choose("Select Proxmox target Node", node_choices)
    storages = list_storages(ve, credentials, target_node)
    if not storages:
        raise PluginError(f"No VM-capable Storage was found on Node {target_node}.")
    datastore = _choose("Select Proxmox Storage", [
        (str(s["storage"]), f"{s['storage']} ({s.get('type','unknown')})") for s in storages
    ])
    disk_size = int(_prompt("Disk size (GiB)", 16))

    tf_prefix = re.sub(r"[^A-Za-z0-9]+", "_", clean_prefix)
    tf_suffix = re.sub(r"[^A-Za-z0-9]+", "_", clean_suffix)
    tf_label = f"{tf_prefix}_{tf_suffix}" if tf_prefix else tf_suffix
    if not re.match(r"^[A-Za-z_]", tf_label):
        tf_label = "r_" + tf_label

    return {
        "id": f"{inventory_id:09d}",
        "type": "pve-vm",
        "state": "pending",
        "ve_id": str(ve["id"]).zfill(4),
        "vmid": inventory_id,
        "terraform_label": tf_label,
        "name": name,
        "node_name": target_node,
        "description": f"Managed by TIAC/Terraform | VEID: {str(ve['id']).zfill(4)} | Inventory ID: {inventory_id:09d}",
        "tags": ["tiac", "terraform", f"ve-{str(ve['id']).zfill(4)}", f"inv-{inventory_id:09d}"],
        "started": True,
        "clone": {
            "source_vm_id": int(template["source_vm_id"]),
            "source_node_name": live_template["node"],
            "full": True,
        },
        "disk": {
            "scsi0": {
                "datastore_id": datastore,
                "size_gb": disk_size,
                "iothread": True,
            }
        },
    }


def _inspect_inventory_resource(
    item: dict[str, Any],
    resource: dict[str, Any] | None,
) -> dict[str, Any]:
    if resource is None:
        return {"status": "absent"}
    if str(resource.get("name", "")) == str(item.get("name", "")):
        return {"status": "match", "resource": resource}
    return {
        "status": "conflict",
        "resource": resource,
        "reason": f"VMID {item['vmid']} belongs to {resource.get('name') or '(unnamed object)'}",
    }


def inspect_inventory_item(
    ve: dict[str, Any],
    credentials: dict[str, str],
    item: dict[str, Any],
) -> dict[str, Any]:
    resource = get_vm_resource(ve, credentials, int(item["vmid"]))
    return _inspect_inventory_resource(item, resource)


def inspect_inventory_items(
    ve: dict[str, Any],
    credentials: dict[str, str],
    items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Inspect multiple inventory records using one Proxmox resource query."""
    resources = {
        int(resource["vmid"]): resource
        for resource in list_vm_resources(ve, credentials)
        if "vmid" in resource
    }
    return {
        str(item["id"]): _inspect_inventory_resource(
            item,
            resources.get(int(item["vmid"])),
        )
        for item in items
    }


def render_provider(ve: dict[str, Any], alias: str, variable_name: str) -> dict[str, str]:
    endpoint = f"https://{ve['host']}:{int(ve['port'])}/"
    insecure = str(not bool(ve.get("verify_tls", True))).lower()
    return {
        "variables.tf": f'variable "{variable_name}" {{\n  type = string\n  sensitive = true\n}}\n',
        "providers.tf": (
            'provider "proxmox" {\n'
            f'  alias = {json.dumps(alias)}\n'
            f'  endpoint = {json.dumps(endpoint)}\n'
            f'  api_token = var.{variable_name}\n'
            f'  insecure = {insecure}\n'
            '}\n'
        ),
    }


def render_resource(item: dict[str, Any], provider_alias: str) -> str:
    lines = [
        f'# TIAC Inventory ID: {item["id"]}',
        f'# VE ID: {item["ve_id"]}',
        f'resource "proxmox_cloned_vm" "{item["terraform_label"]}" {{',
        f'  provider = proxmox.{provider_alias}',
        f'  id = {int(item["vmid"])}',
        f'  node_name = {json.dumps(item["node_name"])}',
        f'  name = {json.dumps(item["name"])}',
        f'  description = {json.dumps(item["description"])}',
        '  tags = [' + ', '.join(json.dumps(t) for t in item["tags"]) + ']',
        f'  started = {str(bool(item["started"])).lower()}',
        '  clone = {',
        f'    source_vm_id = {int(item["clone"]["source_vm_id"])}',
    ]
    if item["clone"].get("source_node_name"):
        lines.append(f'    source_node_name = {json.dumps(item["clone"]["source_node_name"])}')
    lines += [
        f'    full = {str(bool(item["clone"]["full"])).lower()}',
        '  }',
        '  disk = {',
        '    scsi0 = {',
        f'      datastore_id = {json.dumps(item["disk"]["scsi0"]["datastore_id"])}',
        f'      size_gb = {int(item["disk"]["scsi0"]["size_gb"])}',
        f'      iothread = {str(bool(item["disk"]["scsi0"]["iothread"])).lower()}',
        '    }',
        '  }',
        '}',
        '',
    ]
    return "\n".join(lines)
