"""The versioned profile registry (C7 apply substrate).

See `ap_registry.profile_registry.ProfileRegistry` and the "Standard registry, gate seam,
dry-run" section of CLAUDE.md for the full architecture.
"""

from ap_registry.profile_registry import ProfileRegistry, ProfileRegistryError

__all__ = ["ProfileRegistry", "ProfileRegistryError"]
