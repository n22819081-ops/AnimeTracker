from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QLabel,QLineEdit,QListWidget,QMessageBox,QPushButton,QVBoxLayout

from ..production.adoption import ExistingProfileValidation,ProfileAdoptionService
from ..production.profile import ProductionProfile


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


class FirstRunDialog(QDialog):
    def __init__(self,target:ProductionProfile,existing:ProductionProfile|None=None,parent=None,*,validation:ExistingProfileValidation|None=None):
        super().__init__(parent);self.target=target;self.existing=existing;self.choice="POSTPONE";self.setWindowTitle("Welcome to Anime Tracker");self.resize(680,470);layout=QVBoxLayout(self)
        title=QLabel("Anime Tracker 1.0.0");title.setObjectName("pageTitle");layout.addWidget(title)
        detail=QLabel("Anime Tracker reads your configured Jellyfin folders but never renames, moves, replaces, or deletes media. First run does not scan Jellyfin, refresh AniList, send Discord messages, or create scheduled tasks.");detail.setWordWrap(True);layout.addWidget(detail)
        layout.addWidget(QLabel(f"Per-user data location:\n{target.root}"))
        if existing:
            counts=(validation.counts if validation else {}) or {}
            found=QLabel(f"Existing project-local profile detected and validated:\n{existing.root}\n\n{counts.get('active_titles','?')} active titles · {counts.get('archived_records','?')} archived/orphaned · {counts.get('baseline_rows','?')} baselines · {counts.get('review_cases','?')} review cases\n\nAdoption copies and verifies it. The source remains available as rollback.");found.setWordWrap(True);found.setObjectName("profileBanner");layout.addWidget(found)
        elif validation:
            unavailable=QLabel(f"Existing-profile adoption is unavailable.\nChecked: {validation.path}\nReason: {validation.reason}");unavailable.setWordWrap(True);unavailable.setObjectName("muted");layout.addWidget(unavailable)
        create=QPushButton("Create Clean Profile");create.setObjectName("primary");create.clicked.connect(lambda:self._select("CLEAN"));layout.addWidget(create)
        self.adopt=QPushButton("Review Existing Profile Adoption");self.adopt.setEnabled(existing is not None);self.adopt.clicked.connect(lambda:self._select("ADOPT"));layout.addWidget(self.adopt)
        self.use_existing=QPushButton("Use Project-Local Profile for Now");self.use_existing.setEnabled(existing is not None);self.use_existing.clicked.connect(lambda:self._select("USE_EXISTING"));layout.addWidget(self.use_existing)
        postpone=QPushButton("Postpone and Exit");postpone.clicked.connect(self.reject);layout.addWidget(postpone);layout.addStretch()
    def _select(self,choice):self.choice=choice;self.accept()


class ProfileAdoptionDialog(QDialog):
    def __init__(self,service:ProfileAdoptionService,parent=None):
        super().__init__(parent);self.service=service;self.result=None;self.setWindowTitle("Adopt Existing Anime Tracker Profile");self.resize(720,500);layout=QVBoxLayout(self);preview=service.preview()
        title=QLabel("Verify and copy existing profile");title.setObjectName("pageTitle");layout.addWidget(title)
        counts=preview.get("counts",{});detail=QLabel(f"Source:\n{preview['source']}\n\nTarget:\n{preview['target']}\n\nValidation: {preview.get('integrity')} integrity · {preview.get('foreign_key_violations')} foreign-key violations · schema {preview.get('schema_version')}\nCounts: {counts.get('active_titles','?')} active · {counts.get('archived_records','?')} archived/orphaned · {counts.get('baseline_rows','?')} baselines · {counts.get('review_cases','?')} reviews\n\nThe source remains unchanged as rollback. A verified pre-adoption backup is created before copying. Discord delivery remains disabled and no test message is sent.");detail.setWordWrap(True);layout.addWidget(detail)
        self.status=QLabel("Ready for explicit confirmation.");self.status.setWordWrap(True);layout.addWidget(self.status);buttons=QDialogButtonBox(QDialogButtonBox.Cancel);run=buttons.addButton("Adopt and Verify",QDialogButtonBox.AcceptRole);buttons.rejected.connect(self.reject);run.clicked.connect(self._run);layout.addWidget(buttons)
    def _run(self):
        if QMessageBox.question(self,"Confirm profile adoption","Copy and verify the existing profile now? The source profile will be retained.")!=QMessageBox.Yes:return
        try:self.result=self.service.adopt(approved=True)
        except Exception as exc:self.status.setText(f"Adoption failed safely: {type(exc).__name__}: {exc}");return
        self.status.setText("Profile adoption completed and verified.");self.accept()
