# MrFreeTool version metadata.
#
# Single source of truth for the version number.  ``package.xml`` and the
# GitHub release workflow read this file, so bumping the version in one place
# is enough.

VERSION = (1, 0, 0)
VERSION_STRING = ".".join(str(part) for part in VERSION)
