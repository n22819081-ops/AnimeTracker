from __future__ import annotations

import argparse
import json
import sys

from .profile import DEFAULT_PRODUCTION_PROFILE,ProductionProfile
from .scheduled import ScheduledCheckRunner,ScheduledRunStatus


def main(argv=None)->int:
    parser=argparse.ArgumentParser();parser.add_argument("--profile",default=str(DEFAULT_PRODUCTION_PROFILE));args=parser.parse_args(argv)
    profile=ProductionProfile(__import__("pathlib").Path(args.profile));result=ScheduledCheckRunner(profile).run();value=json.dumps({"run_id":result.run_id,"status":result.status,"refresh_success":result.refresh_success,"refresh_failed":result.refresh_failed,"inventory_result":result.inventory_result,"delivered":result.delivered,"warnings":result.warnings})
    if sys.stdout is not None:print(value)
    return 0 if result.status in {ScheduledRunStatus.SUCCESS.value,ScheduledRunStatus.PARTIAL_SUCCESS.value,ScheduledRunStatus.OFFLINE_CACHE_ONLY.value} else 2 if result.status==ScheduledRunStatus.ALREADY_RUNNING.value else 1


if __name__=="__main__":raise SystemExit(main())
