# import sys
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient
from synology_api import filestation


def randomized_password(length: int = 16):
    import random
    import string

    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


load_dotenv()

SYNO_IP = os.getenv("SYNO_IP")
SYNO_PORT = os.getenv("SYNO_PORT")
SYNO_USER = os.getenv("SYNO_USER")
SYNO_PASS = os.getenv("SYNO_PASSWORD")

creds = {
    "ip": SYNO_IP,
    "port": int(SYNO_PORT),
    "user": SYNO_USER,
    "password": SYNO_PASS,
}

FILESTATION = filestation.FileStation(
    creds.get("ip"),
    creds.get("port"),
    creds.get("user"),
    creds.get("password"),
    secure=True,
    cert_verify=False,
    dsm_version=7,
    debug=False,
    otp_code=None,
    interactive_output=False,
)

URI = os.getenv("MONGODB")

client = MongoClient(URI)
db = client.busse_data

PKG = db.pkg
MFG = db.mfg
COMP = db.components

LINK_TRACKER = client.synology_data.link_tracker


def update_link_tracker(link: str, password: str):
    now = datetime.now()
    expires_at = now + timedelta(minutes=30)
    obj = {
        "link": link,
        "password": password,
        "expires_at": expires_at,
    }
    LINK_TRACKER.update_one({"links": {"$exists": True}}, {"$push": {"links": obj}})


def delete_shared_link(link: str):
    global FILESTATION

    link_id = link.split("/")[-1]

    return FILESTATION.delete_shared_link(link_id)


def loop_over_links():
    global LINK_TRACKER

    links = []

    not_expired = []

    docs = list(LINK_TRACKER.find({}))

    if docs:
        for doc in docs:
            links.extend(doc["links"])

        for link in links:
            print(
                "Checking link: ",
                link["link"],
                "expires at: ",
                link["expires_at"],
                "now: ",
                datetime.now(),
                "delete: ",
                link["expires_at"] < datetime.now(),
            )

            if link["expires_at"] > datetime.now():
                not_expired.append(link)
            else:
                print("Deleting link: ", link["link"])
                delete_shared_link(link["link"])

        LINK_TRACKER.update_one({}, {"$set": {"links": not_expired}})


scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(application: FastAPI):
    global CUSTOMERS
    # scheduler.add_job(loop_over_links, "interval", minutes=20)
    yield
    loop_over_links()


app = FastAPI(
    lifespan=lifespan,
)

templates = Jinja2Templates(directory="templates")

origins = [
    "http://docs.bhd-ny.com",
    "https://docs.bhd-ny.com",
    "http://localhost",
    "http://localhost:8742",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/static", StaticFiles(directory=os.path.join(os.getcwd(), "static")), name="static"
)


PASSWORD = randomized_password()


def show_where_used(doc_type: str, document: str):
    document = document.replace(" ", "").strip().upper()

    doc_types = [
        "mss_msd_id",
        "mi_id",
        "qas",
        "pss_id",  # pkg]
        "mssmsd_id",
        "qas_id",
        "mi_id",
        "pss_id",
    ]  # mfg

    if doc_type not in doc_types:
        raise HTTPException(status_code=404, detail="Invalid document type")

    docs_to_search = []

    docs_to_search.append(doc_type)

    if doc_type == "mss_msd_id":
        docs_to_search.append("mssmsd_id")
    elif doc_type == "mssmsd_id":
        docs_to_search.append("mss_msd_id")

    if doc_type == "qas":
        docs_to_search.append("qas_id")
    elif doc_type == "qas_id":
        docs_to_search.append("qas")

    docs = []
    is_component = False

    for dtype in docs_to_search:
        pkg_docs = PKG.find({dtype: {"$regex": document, "$options": "i"}})
        if pkg_docs:
            docs.extend(pkg_docs)

        mfg_docs = MFG.find({dtype: {"$regex": document, "$options": "i"}})
        if mfg_docs:
            docs.extend(mfg_docs)

        comp_docs = COMP.find({dtype: {"$regex": document, "$options": "i"}})
        if comp_docs:
            docs.extend(comp_docs)
            is_component = True

    if docs:
        return [doc["part"] for doc in docs], "QAS-R" if is_component else "QAS"

    return [], None


def show_where_used_cli():
    options = {
        "mss": "mss_msd_id",
        "mi": "mi_id",
        "qas": "qas",
        "pss": "pss_id",
    }

    opts_list = list(options.keys())

    for i, opt in enumerate(opts_list):
        print(f"{i+1}. {opt}")

    choice = int(input("Enter choice: ")) - 1

    if choice < 0 or choice >= len(opts_list):
        print("Invalid choice")
        return

    document = input("Enter document number: ").strip().upper()

    if not document:
        print("Invalid document number")
        return

    docs = PKG.find({options[opts_list[choice]]: {"$regex": document, "$options": "i"}})

    if docs:
        return docs

    return None


def print_list_recursive(folder_path):
    global FILESTATION
    list_of_files = FILESTATION.get_file_list(
        folder_path=folder_path,
    )
    for file in list_of_files["data"]["files"]:
        if file["isdir"]:
            print("->", file["name"])
            print_list_recursive(file["path"])
        else:
            print("\t", file["name"])


def dmr_create_sharing_link(
    part: str,
    password: str,
    path: str = "Device Master Record (DMR) + Artwork",
):
    global FILESTATION

    root_path = r"/Document Control/Document Control @ Busse/PDF Controlled Documents"

    files = FILESTATION.get_file_list(
        folder_path=root_path + f"/{path}",
    )

    for file in files["data"]["files"]:
        if file["isdir"]:
            for sub_file in FILESTATION.get_file_list(
                folder_path=file["path"],
            )["data"]["files"]:
                if sub_file["name"] == part:
                    expires_at = datetime.now() + timedelta(minutes=5)
                    # print("expires at: ", expires_at)

                    sharing_link = FILESTATION.create_sharing_link(
                        path=sub_file["path"],
                        password=password,
                        date_expired=expires_at,
                    )["data"]["links"][0]["url"].replace(":5001", "")

                    update_link_tracker(sharing_link, password)

                    return sharing_link


def qas_create_sharing_link(
    qas_id: str,
    password: str,
    path: str = "Quality Assurance Specification (QAS, QAS-R) PDF",
):
    global FILESTATION

    root_path = r"/Document Control/Document Control @ Busse/PDF Controlled Documents"

    files = FILESTATION.get_file_list(
        folder_path=root_path + f"/{path}",
    )

    regex_pattern = re.compile(rf"{qas_id}", re.IGNORECASE)

    for file in files["data"]["files"]:
        if file["isdir"]:
            for sub_file in FILESTATION.get_file_list(
                folder_path=file["path"],
            )["data"]["files"]:
                if regex_pattern.search(sub_file["name"]):
                    sharing_link = FILESTATION.create_sharing_link(
                        path=sub_file["path"],
                        password=password,
                        date_expired=datetime.now() + timedelta(minutes=30),
                    )["data"]["links"][0]["url"].replace(":5001", "")

                    update_link_tracker(sharing_link, password)

                    return sharing_link


def flat_path_create_sharing_link(filename_partial: str, password: str, path: str):
    global FILESTATION

    root_path = r"/Document Control/Document Control @ Busse/PDF Controlled Documents"

    files = FILESTATION.get_file_list(
        folder_path=root_path + f"/{path}",
    )

    for file in files["data"]["files"]:
        if re.search(rf"{filename_partial}", file["name"], re.IGNORECASE):
            sharing_link = FILESTATION.create_sharing_link(
                path=file["path"],
                password=password,
                date_expired=datetime.now() + timedelta(minutes=30),
            )["data"]["links"][0]["url"].replace(":5001", "")

            update_link_tracker(sharing_link, password)

            return sharing_link


def fm_get_details(part: str):
    doc = PKG.find_one({"part": part})
    doc_type = "pkg"
    if not doc:
        doc = MFG.find_one({"part": part})
        doc_type = "mfg"

        if not doc:
            doc = COMP.find_one({"part": part})
            doc_type = "component"

            if not doc:
                return None, None

    return doc, doc_type


def fm_get_dmr_details(doc: dict[str, str], pkg_or_mfg: str, part: str):
    generated_password = randomized_password()

    if pkg_or_mfg == "pkg" or pkg_or_mfg == "component":
        mss_id = doc.get("mss_msd_id", "").upper().strip()
        qas_id = doc.get("qas", "").upper().strip()
        mi_id = doc.get("mi_id", "").upper().strip()
        pss_id = doc.get("pss_id", "").upper().strip()

        dmr_link = dmr_create_sharing_link(part, generated_password)

        mi_link = flat_path_create_sharing_link(
            mi_id, generated_password, "PKG Manufacturing Instructions (MI) PDF"
        )
        if not mi_link:
            mi_link = flat_path_create_sharing_link(
                mi_id, generated_password, "MFG Manufacturing Instructions (MI) PDF"
            )

        dmr_details = {
            "mss": {
                "name": "MSS " + mss_id,
                "link": flat_path_create_sharing_link(
                    mss_id, generated_password, "Machine Setup Sheet (MSS) PDF"
                ),
            },
            "mi": {
                "name": "MI " + mi_id,
                "link": mi_link,
            },
            "qas": {
                "name": f"{'QAS' if pkg_or_mfg == 'pkg' else 'QAS-R'} {qas_id}",
                "link": qas_create_sharing_link(qas_id, generated_password),
            },
            "pss": {
                "name": "PSS " + pss_id,
                "link": flat_path_create_sharing_link(
                    pss_id, generated_password, "Post Sterilization Specification (PSS)"
                ),
            },
            "shipper_label": {
                "name": doc.get("shipper_label", "").upper(),
                "link": dmr_link,
            },
            "content_label": {
                "name": doc.get("content_card", "").upper(),
                "link": dmr_link,
            },
            "dispenser_label": {
                "name": doc.get("dispenser_label", "").upper(),
                "link": dmr_link,
            },
            "print_mat": {"name": doc.get("print_mat", "").upper(), "link": dmr_link},
            "dmr": {
                "name": "DMR " + part.upper(),
                "link": dmr_link,
            },
            "dco": {
                "name": doc.get("dco_number", "").upper(),
                "link": None,
            },
            "ink": {"name": doc.get("ink_part_number", "").upper(), "link": None},
            "special_instructions": {
                "name": doc.get("special_instructions", "").upper(),
                "link": None,
            },
        }

    elif pkg_or_mfg == "mfg":
        mss_id = doc.get("mssmsd_id", "").upper().strip()
        qas_id = doc.get("qas_id", "").upper().strip()
        mi_id = doc.get("mi_id", "").upper().strip()
        pss_id = doc.get("pss_id", "").upper().strip()

        dmr_link = dmr_create_sharing_link(part, generated_password)

        mi_link = flat_path_create_sharing_link(
            mi_id,
            generated_password,
            "MFG Manufacturing Instructions (MI) PDF",
        )
        if not mi_link:
            mi_link = flat_path_create_sharing_link(
                mi_id, generated_password, "PKG Manufacturing Instructions (MI) PDF"
            )

        dmr_details = {
            "mss": {
                "name": "MSS " + mss_id,
                "link": flat_path_create_sharing_link(
                    mss_id, generated_password, "Machine Setup Sheet (MSS) PDF"
                ),
            },
            "mi": {
                "name": "MI " + mi_id,
                "link": mi_link,
            },
            "qas": {
                "name": "QAS " + qas_id,
                "link": qas_create_sharing_link(qas_id, generated_password),
            },
            "pss": {
                "name": "PSS " + pss_id,
                "link": flat_path_create_sharing_link(
                    pss_id, generated_password, "Post Sterilization Specification (PSS)"
                ),
            },
            "shipper_label": {
                "name": doc.get("shipper_label", "").upper(),
                "link": dmr_link,
            },
            "content_label": {
                "name": doc.get("content_card", "").upper(),
                "link": dmr_link,
            },
            "dispenser_label": {
                "name": doc.get("dispenser_label", "").upper(),
                "link": dmr_link,
            },
            "print_mat": {
                "name": doc.get("print_mat", "").upper(),
                "link": dmr_link,
            },
            "dmr": {
                "name": "DMR " + part.upper(),
                "link": dmr_link,
            },
            "dco": {
                "name": doc.get("dco_number", "").upper(),
                "link": None,
            },
            "ink": {"name": doc.get("ink_part_number", "").upper(), "link": None},
            "special_instructions": {
                "name": doc.get("special_instructions", "").upper(),
                "link": None,
            },
        }

    return dmr_details, generated_password


@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/show_where_used")
def show_where_used_endpoint(request: Request, doc_type: str, document: str):
    doc_type = doc_type.strip().lower()
    document = document.strip().upper()

    parts, qas_type = show_where_used(doc_type=doc_type, document=document)

    if not parts:
        return HTTPException(status_code=404, detail="Document not found")

    return templates.TemplateResponse(
        "swu.html",
        {
            "request": request,
            "parts": parts,
            "doc_type": doc_type.upper(),
            "qas_type": qas_type.upper() if qas_type else None,
            "document": document.upper(),
        },
    )


@app.get("/dmr")
def get_dmr_details_endpoint(request: Request, part: str):
    part = part.strip().upper()

    doc, doc_type = fm_get_details(part)

    if not doc:
        return HTTPException(status_code=404, detail="Part not found")

    details, password = fm_get_dmr_details(doc, doc_type, part)

    # return {"details": details, "password": password}
    return templates.TemplateResponse(
        "dmr_details.html",
        {"request": request, "part": part, "dmr": details, "password": password},
    )


if __name__ == "__main__":
    import uvicorn

    loop_over_links()

    scheduler.add_job(loop_over_links, "interval", minutes=20)

    uvicorn.run("main:app", host="0.0.0.0", port=8742, reload=True)
