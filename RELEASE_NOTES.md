# Stable 0.2.24

Promotes the accepted v0.2.24 product and installer without changing their bytes or numeric version. This stable version includes fixed container isolation, explicit legacy migration, GPU access and switching, the network switch, the 25-package Ubuntu APT development environment, independent filesystem mounts, standard lifecycle coordination and shared inline menus with corrected resize handling.

The release branch contains stable product/installer source and shared build/installation files. Stable assets are mas.pyz, mas-install.pyz and SHA256SUMS. Automated tests are supplied separately by the immutable v0.2.24 test release.

Installation reads source only from release and product/installer assets from the selected stable release. Matching stable verification and detailed measured limits are recorded on main in IMPLEMENTED.md and TEST_COVERAGE.md.
