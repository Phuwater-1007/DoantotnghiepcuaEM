from __future__ import annotations

from dataclasses import dataclass

from vehicle_counting_system.application.services.activity_log_service import ActivityLogService
from vehicle_counting_system.application.services.admin_service import AdminService
from vehicle_counting_system.application.services.auth_service import AuthService
from vehicle_counting_system.application.services.dashboard_service import DashboardService
from vehicle_counting_system.application.services.monitoring_service import MonitoringService
from vehicle_counting_system.application.services.report_service import ReportService
from vehicle_counting_system.application.services.source_service import SourceService
from vehicle_counting_system.infrastructure.persistence.sqlite_db import SQLiteDatabase


@dataclass
class AppContainer:
    db: SQLiteDatabase
    auth_service: AuthService
    source_service: SourceService
    dashboard_service: DashboardService
    report_service: ReportService
    monitoring_service: MonitoringService
    activity_log_service: ActivityLogService
    admin_service: AdminService


def build_container() -> AppContainer:
    db = SQLiteDatabase()
    auth_service = AuthService(db)
    source_service = SourceService(db)
    report_service = ReportService(db)
    dashboard_service = DashboardService(db, source_service)
    monitoring_service = MonitoringService(db, source_service, report_service)
    activity_log_service = ActivityLogService(db)
    admin_service = AdminService(db, monitoring_service)

    db.init_schema()
    db.recover_stale_sessions()
    db.fix_report_timezone_data()
    db.seed_defaults(auth_service)

    return AppContainer(
        db=db,
        auth_service=auth_service,
        source_service=source_service,
        dashboard_service=dashboard_service,
        report_service=report_service,
        monitoring_service=monitoring_service,
        activity_log_service=activity_log_service,
        admin_service=admin_service,
    )
