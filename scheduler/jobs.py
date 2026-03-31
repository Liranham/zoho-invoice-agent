"""
Scheduled automation jobs.

Runs in a daemon thread when the agent is in server mode (Render).
Uses the `schedule` library for lightweight cron-like scheduling.
"""

import logging
import threading
import time

import schedule

from zoho.invoices import InvoiceService
from config.settings import Settings

logger = logging.getLogger(__name__)


class JobScheduler:
    def __init__(self, invoice_service: InvoiceService, settings: Settings):
        self.invoice_service = invoice_service
        self.settings = settings
        self._running = False

    def setup_jobs(self):
        """Configure scheduled jobs based on settings.

        Cron format: "daily:HH:MM" or "weekly:DAY:HH:MM" or "monthly:DD:HH:MM"
        """
        cron = self.settings.scheduler.recurring_cron
        if not cron:
            logger.info("No recurring cron configured, scheduler idle")
            return

        parts = cron.split(":")
        freq = parts[0].lower()

        if freq == "daily" and len(parts) == 3:
            time_str = f"{parts[1]}:{parts[2]}"
            schedule.every().day.at(time_str).do(self._recurring_job)
            logger.info("Scheduled daily job at %s", time_str)

        elif freq == "weekly" and len(parts) == 4:
            day = parts[1].lower()
            time_str = f"{parts[2]}:{parts[3]}"
            getattr(schedule.every(), day).at(time_str).do(self._recurring_job)
            logger.info("Scheduled weekly job on %s at %s", day, time_str)

        elif freq == "monthly" and len(parts) == 4:
            # schedule lib doesn't support monthly natively, use daily + day check
            self._monthly_day = int(parts[1])
            time_str = f"{parts[2]}:{parts[3]}"
            schedule.every().day.at(time_str).do(self._monthly_check)
            logger.info(
                "Scheduled monthly job on day %d at %s",
                self._monthly_day,
                time_str,
            )
        else:
            logger.warning("Unrecognized cron format: %s", cron)

    def _recurring_job(self):
        """Override this or configure via settings to define what invoices to create."""
        logger.info("Recurring invoice job triggered — no template configured yet")

    def _monthly_check(self):
        """Run the recurring job only on the configured day of the month."""
        from datetime import datetime

        if datetime.now().day == self._monthly_day:
            self._recurring_job()

    def start(self):
        self._running = True
        self.setup_jobs()

        def _loop():
            while self._running:
                schedule.run_pending()
                time.sleep(30)

        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()
        logger.info("Scheduler started")

    def stop(self):
        self._running = False
