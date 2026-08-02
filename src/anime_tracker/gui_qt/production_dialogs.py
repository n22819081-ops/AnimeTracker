from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QLabel,QLineEdit,QListWidget,QVBoxLayout


WIZARD_STEPS=("Welcome","Existing tracker detected","Backup verification","Data inventory","Migration preview","Known uncertainties","Discord credential migration","Jellyfin roots","AniList baseline refresh","Jellyfin scan preview","Mapping review","Notification activation","Scheduling setup","Final comparison","Cutover confirmation")


class ProductionMigrationWizard(QDialog):
    def __init__(self,profile,parent=None):
        super().__init__(parent);self.profile=profile;self.setWindowTitle("Anime Tracker Production Migration");self.resize(900,650);layout=QVBoxLayout(self)
        title=QLabel("Production migration is pending");title.setObjectName("pageTitle");layout.addWidget(title)
        warning=QLabel("Opening this wizard does not migrate data, read credentials, scan Jellyfin, send Discord messages, change Task Scheduler, or approve cutover.");warning.setObjectName("profileBanner");warning.setWordWrap(True);layout.addWidget(warning)
        self.steps=QListWidget();self.steps.addItems(WIZARD_STEPS);self.steps.setCurrentRow(0);layout.addWidget(self.steps,1)
        self.summary=QLabel("Use the documented migration command after reviewing the verified backup. Every production activation remains explicit.");self.summary.setWordWrap(True);layout.addWidget(self.summary)
        buttons=QDialogButtonBox();postpone=buttons.addButton("Postpone",QDialogButtonBox.RejectRole);review=buttons.addButton("Review Migration Guide",QDialogButtonBox.ActionRole);review.setEnabled(False);buttons.rejected.connect(self.reject);layout.addWidget(buttons)


class CutoverConfirmationDialog(QDialog):
    PHRASE="MAKE MODERN TRACKER PRIMARY"
    def __init__(self,summary:dict,parent=None):
        super().__init__(parent);self.setWindowTitle("Production Cutover Confirmation");self.resize(700,560);layout=QVBoxLayout(self);layout.addWidget(QLabel("Final production cutover remains pending"))
        details=QLabel("\n".join(f"{key.replace('_',' ').title()}: {value}" for key,value in summary.items()));details.setWordWrap(True);layout.addWidget(details,1)
        layout.addWidget(QLabel(f"Type exactly: {self.PHRASE}"));self.confirm=QLineEdit();layout.addWidget(self.confirm)
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel);self.approve=buttons.addButton("Approve Cutover",QDialogButtonBox.AcceptRole);self.approve.setEnabled(False);self.confirm.textChanged.connect(lambda value:self.approve.setEnabled(value==self.PHRASE));buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
