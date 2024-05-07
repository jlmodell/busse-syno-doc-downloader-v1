# import sys
import os
import re
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
from pymongo import MongoClient
from synology_api import filestation

options = {
    "swu": "Show where used",
    "find": "Find part details",
}

opts_list = list(options.keys())

for i, opt in enumerate(opts_list):
    print(f"{i+1}. {opt}")

choice = int(input("Enter choice: ")) - 1

if choice < 0 or choice >= len(opts_list):
    print("Invalid choice")
    sys.exit(1)


def randomized_password(length: int = 16):
    import random
    import string

    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


PASSWORD = randomized_password()

load_dotenv()

URI = os.getenv("MONGODB")

client = MongoClient(URI)
db = client.busse_data

PKG = db.pkg
MFG = db.mfg

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


def show_where_used():
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
        for doc in docs:
            print(doc["part"])


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
    part: str, path: str = "Device Master Record (DMR) + Artwork"
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
                    print("expires at: ", expires_at)
                    return FILESTATION.create_sharing_link(
                        path=sub_file["path"],
                        password=PASSWORD,
                        date_expired=expires_at,
                    )["data"]["links"][0]["url"].replace(":5001", "")


def qas_create_sharing_link(
    qas_id: str, path: str = "Quality Assurance Specification (QAS, QAS-R) PDF"
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
                    return FILESTATION.create_sharing_link(
                        path=sub_file["path"],
                        password=PASSWORD,
                        date_expired=datetime.now() + timedelta(minutes=30),
                    )["data"]["links"][0]["url"].replace(":5001", "")


def flat_path_create_sharing_link(filename_partial: str, path: str):
    global FILESTATION

    root_path = r"/Document Control/Document Control @ Busse/PDF Controlled Documents"

    files = FILESTATION.get_file_list(
        folder_path=root_path + f"/{path}",
    )

    for file in files["data"]["files"]:
        # print(
        #     file["name"],
        #     filename_partial,
        #     re.search(rf"{filename_partial}", file["name"], re.IGNORECASE),
        # )

        if re.search(rf"{filename_partial}", file["name"], re.IGNORECASE):
            return FILESTATION.create_sharing_link(
                path=file["path"],
                password=PASSWORD,
                date_expired=datetime.now() + timedelta(minutes=30),
            )["data"]["links"][0]["url"].replace(":5001", "")


def fm_get_details(part: str):
    doc = PKG.find_one({"part": part})
    doc_type = "pkg"
    if not doc:
        doc = MFG.find_one({"part": part})
        doc_type = "mfg"
        if not doc:
            return None, None

    return doc, doc_type


def fm_get_dmr_details(doc: dict[str, str], pkg_or_mfg: str, part: str):
    global PASSWORD

    if pkg_or_mfg == "pkg":
        mss_id = doc.get("mss_msd_id", "").upper().strip()
        qas_id = doc.get("qas", "").upper().strip()
        mi_id = doc.get("mi_id", "").upper().strip()
        pss_id = doc.get("pss_id", "").upper().strip()

        dmr_link = dmr_create_sharing_link(part)

        mi_link = flat_path_create_sharing_link(
            mi_id, "PKG Manufacturing Instructions (MI) PDF"
        )
        if not mi_link:
            mi_link = flat_path_create_sharing_link(
                mi_id, "MFG Manufacturing Instructions (MI) PDF"
            )

        dmr_details = {
            "mss": {
                "name": "MSS " + mss_id,
                "link": flat_path_create_sharing_link(
                    mss_id, "Machine Setup Sheet (MSS) PDF"
                ),
            },
            "mi": {
                "name": "MI " + mi_id,
                "link": mi_link,
            },
            "qas": {
                "name": "QAS " + qas_id,
                "link": qas_create_sharing_link(qas_id),
            },
            "pss": {
                "name": "PSS " + pss_id,
                "link": flat_path_create_sharing_link(
                    pss_id, "Post Sterilization Specification (PSS)"
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

        dmr_link = dmr_create_sharing_link(part)

        mi_link = flat_path_create_sharing_link(
            mi_id,
            "MFG Manufacturing Instructions (MI) PDF",
        )
        if not mi_link:
            mi_link = flat_path_create_sharing_link(
                mi_id, "PKG Manufacturing Instructions (MI) PDF"
            )

        dmr_details = {
            "mss": {
                "name": "MSS " + mss_id,
                "link": flat_path_create_sharing_link(
                    mss_id, "Machine Setup Sheet (MSS) PDF"
                ),
            },
            "mi": {
                "name": "MI " + mi_id,
                "link": mi_link,
            },
            "qas": {
                "name": "QAS " + qas_id,
                "link": qas_create_sharing_link(qas_id),
            },
            "pss": {
                "name": "PSS " + pss_id,
                "link": flat_path_create_sharing_link(
                    pss_id, "Post Sterilization Specification (PSS)"
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

    return dmr_details


if __name__ == "__main__":
    from time import sleep

    if choice == 0:
        show_where_used()

    else:
        part = input("Enter part number: ").strip().upper()

        doc, doc_type = fm_get_details(part)

        if doc:
            details = fm_get_dmr_details(doc, doc_type, part)

            print()
            print("Details: ")
            print()
            print("Part: ", part)
            print()

            for k, v in details.items():
                output = [k]

                for k1, v1 in v.items():
                    output.append(v1)

                print(f"{output[0].upper()}: {output[1]} -> {output[2]}")

            print("\n\n")

            print(f"The password is: {PASSWORD}")

            import pyperclip

            print(
                "The password is automatically generated and will expire in 30 minutes."
            )
            print("Please do not share the password with anyone.")
            print("The password was saved to your clipboard.")

            pyperclip.copy(PASSWORD)
        else:
            print("Part not found")

    print()
    print("Ctrl + C to exit")

    sleep(100 * 60 * 60)
    sys.exit(0)
