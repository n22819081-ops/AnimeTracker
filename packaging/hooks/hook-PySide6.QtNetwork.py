"""Collect QtNetwork without the build-time QSslSocket capability probe.

The official hook's QSslSocket.supportsSsl() call can block indefinitely on
Windows. Normal Qt dependencies include the Schannel TLS plugin, while Python's
ssl hook collects the OpenSSL runtime used by requests.
"""

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
