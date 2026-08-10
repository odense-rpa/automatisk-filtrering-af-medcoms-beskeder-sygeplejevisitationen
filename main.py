import asyncio
from datetime import datetime, timedelta
import logging
import os
import sys
import argparse

from odk_tools.tracking import Tracker
from kmd_nexus_client import NexusClientManager 
from kmd_nexus_client.tree_helpers import filter_by_path

from process.config import load_excel_mapping, get_regler

from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential, WorkItemStatus

nexus: NexusClientManager
tracker: Tracker
procesnavn = "Automatisk filtrering af Medcoms for Sygeplejevisitation"

async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from populate workqueue!")

    # hent beskeder / aktivitetslisten
    aktivitetsliste = nexus.aktivitetslister.hent_aktivitetsliste(navn="MedCom - Korrespondancer", organisation=None, medarbejder=None)
    # behold kun bekseder fra de sidste 30 dage:
    aktivitetsliste = [x for x in aktivitetsliste if x["date"] > (datetime.today() - timedelta(days=30)).isoformat()]
    # for hver besked, skal borgeren hentes og finde organisationer forbundet til
    for aktivitet in aktivitetsliste:
        cpr = aktivitet["patients"][0]["patientIdentifier"]["identifier"]
        if cpr is None or cpr == "":
            continue
        borger = nexus.borgere.hent_borger(cpr)
        borgers_organisationer = nexus.organisationer.hent_organisationer_for_borger(borger)

        # sammenlign organisationerne med reglerne
        har_ignoreret_organisation = any(org["organization"]["name"] in regler for org in borgers_organisationer)

        if har_ignoreret_organisation:
            continue

        # hvis der ikke er et match, skal data sendes til workqueue for at lave opgave og arkivere besked
        if not har_ignoreret_organisation:

            data = {
                "aktivitet_id": aktivitet["id"],
                "borger_cpr": cpr
            }
            workqueue.add_item(data=data, reference= str(aktivitet["id"]))


        

async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict


            try:
                # Find den rette besked
                borger = nexus.borgere.hent_borger(data["borger_cpr"])
                indbakke = nexus.medcom.hent_alle_beskeder(borger)
                beskedreference = next((b for b in indbakke if b["id"] == data["aktivitet_id"]), None)
                if beskedreference is None:
                    raise ValueError(f"Besked ikke fundet med id: {data['aktivitet_id']}")
                besked_der_skal_arkiveres = nexus.medcom.hent_besked(beskedreference)

                # Opret opgave:
                nexus.opgaver.opret_opgave(
                    objekt=besked_der_skal_arkiveres,
                    opgave_type="Ny visitation sygepleje §138",
                    titel="Ny visitation sygepleje §138 - LK",
                    ansvarlig_organisation="Myndighed Sygeplejerådgivere",
                    start_dato=datetime.today(),
                    forfald_dato=datetime.today()
                )

                # Arkivér besked:
                nexus.medcom.arkiver_besked(besked_der_skal_arkiveres)
                tracker.track_task(procesnavn) 
                
            except (WorkItemError, KeyError, ValueError) as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                logger.error(f"Error processing item: {data}. Error: {e}")
                item.fail(str(e))

    print("hej")

if __name__ == "__main__":
    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    # Initialize external systems for automation here..
    nexus_credential = Credential.get_credential("KMD Nexus - produktion")
    tracking_credential = Credential.get_credential("Odense SQL Server")

    nexus = NexusClientManager(
        client_id=nexus_credential.username,
        client_secret=nexus_credential.password,
        instance=nexus_credential.data["instance"],
    )    

    tracker = Tracker(
        username=tracking_credential.username, 
        password=tracking_credential.password
    )
    
   # Parse command line arguments
    parser = argparse.ArgumentParser(description=procesnavn)
    parser.add_argument(
        "--excel-file",
        default=os.environ.get("EXCEL_MAPPING_PATH"),
        help="Path to the Excel file containing mapping data (default: ./Regelsæt.xlsx)",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Populate the queue with test data and exit",
    )
    args = parser.parse_args()

    # Validate Excel files exists (skip validation for Windows paths on Linux)
    def is_windows_path(path: str) -> bool:
        """Check if path is a Windows path (has drive letter or UNC path)"""
        return (
            (len(path) > 1 and path[1] == ":")
            or path.startswith("\\\\")
            or path.startswith("//")
        )

    # Load excel mapping data once on startup (only if files exist on current system)
    if os.path.isfile(args.excel_file):
        load_excel_mapping(args.excel_file)
    elif not is_windows_path(args.excel_file):
        raise FileNotFoundError(f"Excel file not found: {args.excel_file}")


    # Get rules from excel mapping (implemented in process.config)
    regler = get_regler()

    # Queue management
    if args.queue:
        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue))
        sys.exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))
