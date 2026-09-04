from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime,timezone

from ..notifications_v2.discord import DiscordDeliveryAdapter
from ..notifications_v2.enums import ChannelPurpose,DeliveryResultType
from ..notifications_v2.models import NotificationMessage
from ..notifications_v2.manual import ManualAnnouncementRepository
from .credentials import DpapiCredentialStore,PRIVATE_REFERENCE,SHARED_REFERENCE
from .profile import ProductionProfile


STAGES={1:"PREVIEW_ONLY",2:"CHANNEL_TESTS",3:"PRIVATE_ENABLED",4:"SHARED_ENABLED",5:"WEEKLY_SUMMARIES_ENABLED"}


class ProductionNotificationActivation:
    def __init__(self,profile:ProductionProfile,store=None,adapter=None)->None:self.profile=profile;self.store=store or DpapiCredentialStore(profile.credentials_dir);self.adapter=adapter or DiscordDeliveryAdapter()

    def baseline_preview(self)->dict:
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
            baseline=connection.execute("SELECT count(*) FROM shared_announcement_baselines_v2 WHERE active=1").fetchone()[0];pending=connection.execute("SELECT count(*) FROM notification_outbox WHERE status IN ('PENDING','RETRY_WAIT')").fetchone()[0];drafts=connection.execute("SELECT count(*) FROM manual_announcement_drafts WHERE status='DRAFT'").fetchone()[0]
        return {"baseline_rows":baseline,"pending_outbox":pending,"manual_drafts_held_for_review":drafts,"existing_content_events":0,"existing_episode_events":0,"delivery_enabled":False}

    def accept_baseline(self,*,approved:bool)->dict:
        if not approved:raise PermissionError("Notification baseline acceptance requires explicit approval.")
        preview=self.baseline_preview();bootstrap=self.profile.load_bootstrap();bootstrap.update({"initial_baseline_accepted":True,"notification_baseline_state":"ACCEPTED_NO_FLOOD","baseline_accepted_at":datetime.now(timezone.utc).isoformat(),"initial_events_created":0});self.profile.save_bootstrap(bootstrap);return {**preview,"accepted":True}

    def activate_stage(self,stage:int,*,approved:bool)->dict:
        if not approved:raise PermissionError("Notification activation requires explicit approval.")
        if stage not in STAGES:raise ValueError("Unknown notification activation stage.")
        current=int(self.profile.load_bootstrap().get("notifications_stage",1))
        if stage>current+1:raise ValueError("Notification stages must be activated sequentially.")
        bootstrap=self.profile.load_bootstrap();bootstrap["notifications_stage"]=stage;bootstrap["private_notifications_enabled"]=stage>=3;bootstrap["shared_notifications_enabled"]=stage>=4;bootstrap["weekly_summaries_enabled"]=stage>=5;self.profile.save_bootstrap(bootstrap)
        return {"stage":stage,"name":STAGES[stage],"private_enabled":stage>=3,"shared_enabled":stage>=4,"weekly_enabled":stage>=5}

    def test_channel(self,purpose:ChannelPurpose,*,approved:bool):
        if not approved:raise PermissionError("A Discord test requires explicit approval.")
        reference=PRIVATE_REFERENCE if purpose==ChannelPurpose.PRIVATE_TRACKER else SHARED_REFERENCE
        secret=self.store.retrieve_secret(reference).reveal();message=NotificationMessage(f"production-test-{purpose.value}",purpose,"Anime Tracker Production Test",f"Explicit test for {purpose.value}. No anime event or baseline change is created.",timestamp=datetime.now(timezone.utc));return self.adapter.deliver(secret,message)


class ProductionManualAnnouncementService:
    def __init__(self,profile:ProductionProfile,store=None,adapter=None,repository=None)->None:self.profile=profile;self.store=store or DpapiCredentialStore(profile.credentials_dir);self.adapter=adapter or DiscordDeliveryAdapter();self.repository=repository or ManualAnnouncementRepository(profile.database_path)

    def send_new_on_server(self,items,*,approved:bool,cancel=None)->dict:
        if not approved:raise PermissionError("A shared announcement requires explicit approval.")
        safe_items=tuple({"anilist_id":int(item["anilist_id"]),"title":str(item["title"]).strip()} for item in items if str(item.get("title") or "").strip())
        if not safe_items:raise ValueError("Select at least one title to announce.")
        now=datetime.now(timezone.utc);draft_id=self.repository.create_draft("New on Jellyfin",safe_items,now);self.repository.set_status(draft_id,"PENDING",now)
        body="\n".join(f"• {item['title']}" for item in safe_items);message=NotificationMessage(f"manual-{draft_id}",ChannelPurpose.SHARED_ANNOUNCEMENT,"New on Jellyfin",body,timestamp=now,silent=True)
        try:
            secret=self.store.retrieve_secret(SHARED_REFERENCE).reveal();result=self.adapter.deliver(secret,message,cancel=cancel)
        except Exception:
            self.repository.set_status(draft_id,"FAILED",datetime.now(timezone.utc));raise
        delivered=result.result==DeliveryResultType.DELIVERED;self.repository.set_status(draft_id,"DELIVERED" if delivered else ("CANCELED" if result.result==DeliveryResultType.CANCELED else "FAILED"),datetime.now(timezone.utc))
        return {"draft_id":draft_id,"delivered":delivered,"result":result.result.value,"error":result.error_summary or result.error_type,"titles":len(safe_items)}
