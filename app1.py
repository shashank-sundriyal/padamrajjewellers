# app.py
"""
Jewellery Loan Manager (Firebase + Streamlit)

REQUIREMENTS BEFORE RUNNING:
1. Place `serviceAccountKey.json` (Firebase service account key) in the same folder as this script.
   - Firebase Console -> Project Settings -> Service Accounts -> Generate new private key
2. Create `firebase_config.json` (Web app config) and place it in the same folder:
   {
     "apiKey": "...",
     "authDomain": "...",
     "projectId": "...",
     "storageBucket": "...",
     "messagingSenderId": "...",
     "appId": "..."
   }
3. Install requirements: pip install -r requirements.txt
4. Run: streamlit run app.py

Notes:
- This app uses Firestore (collection names: customers, loans, settings).
- Keep serviceAccountKey.json private (do NOT push to public GitHub).
"""

import streamlit as st
import pandas as pd
import numpy as np
import datetime
import io
import os
import json
from pathlib import Path

# Firebase imports
# Firebase imports
# -------------------- Firebase Initialization --------------------
import json
import firebase_admin
from firebase_admin import credentials, firestore

# Safely initialize Firebase using Streamlit secrets
try:
    if not firebase_admin._apps:
        # Convert AttrDict to pure dict
        firebase_config = json.loads(json.dumps(dict(st.secrets["firebase"])))
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    st.success("✅ Connected to Firebase successfully")
except Exception as e:
    st.error(f"❌ Firebase initialization failed: {e}")
    st.stop()
# ----------------------------------------------------------------


# -------------------------
# File / config names
# -------------------------
# ----------------------------------------------------------------
# Firebase initialization using Streamlit secrets (no local files)
# ----------------------------------------------------------------
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pyrebase
from pathlib import Path

# Initialize Firebase Admin SDK (for Firestore)
try:
    if not firebase_admin._apps:
        firebase_config = json.loads(json.dumps(dict(st.secrets["firebase"])))
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    st.success("✅ Connected to Firebase successfully")
except Exception as e:
    st.error(f"❌ Firebase initialization failed: {e}")
    st.stop()

# Initialize Pyrebase (for Auth)
try:
    # Use same config as Firebase secrets for auth
    pyrebase_config = {
        "apiKey": st.secrets["firebase"].get("api_key", ""),
        "authDomain": f"{st.secrets['firebase']['project_id']}.firebaseapp.com",
        "projectId": st.secrets["firebase"]["project_id"],
        "storageBucket": f"{st.secrets['firebase']['project_id']}.appspot.com",
        "messagingSenderId": st.secrets["firebase"].get("messaging_sender_id", ""),
        "appId": st.secrets["firebase"].get("app_id", ""),
        "databaseURL": ""
    }

    pb = pyrebase.initialize_app(pyrebase_config)
    auth = pb.auth()
    st.success("✅ Firebase Auth ready")

except Exception as e:
    st.warning(f"⚠️ Firebase Auth could not be initialized: {e}")
    auth = None

# ----------------------------------------------------------------
# Export / other app configs
# ----------------------------------------------------------------
EXPORT_NAME = "jewellery_data_export.xlsx"


# -------------------------
# Firestore helpers
# -------------------------
def read_collection_to_df(coll_name):
    docs = db.collection(coll_name).stream()
    rows = []
    for d in docs:
        obj = d.to_dict()
        obj["_id"] = d.id
        rows.append(obj)
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=[])

def get_customers_df():
    df = read_collection_to_df("customers")
    # ensure columns
    expected = ["_id","name","phone","alt_phone","aadhaar","address","notes","created_at"]
    for c in expected:
        if c not in df.columns:
            df[c] = ""
    return df[expected] if not df.empty else df

def get_loans_df():
    df = read_collection_to_df("loans")
    expected = ["_id","customer_id","item_name","jewellery_type","weight","principal","interest_rate",
                "interest_type","cycle_type","keep_date","manual_duration","claimed","claimed_at","created_at"]
    for c in expected:
        if c not in df.columns:
            df[c] = "" if c not in ["principal","interest_rate","weight","manual_duration"] else 0.0
    return df[expected] if not df.empty else df

def get_settings_df():
    docs = list(db.collection("settings").limit(1).stream())
    if not docs:
        default = {
            "company_name":"ABC",
            "currency": "₹",
            "interest_cycle_days": 30,
            "interest_rate_percent": 2.0
        }
        db.collection("settings").add(default)
        return pd.DataFrame([default])
    return pd.DataFrame([docs[0].to_dict()])

def add_customer(payload):
    db.collection("customers").add(payload)

def update_customer(doc_id, payload):
    db.collection("customers").document(doc_id).update(payload)

def delete_customer(doc_id):
    # delete loans of this customer first
    loans = db.collection("loans").where("customer_id","==",doc_id).stream()
    for l in loans:
        db.collection("loans").document(l.id).delete()
    db.collection("customers").document(doc_id).delete()

def add_loan(payload):
    db.collection("loans").add(payload)

def update_loan(doc_id, payload):
    db.collection("loans").document(doc_id).update(payload)

def delete_loan(doc_id):
    db.collection("loans").document(doc_id).delete()

# -------------------------
# Interest utilities
# -------------------------
def parse_date(d):
    if d is None or d == "":
        return datetime.datetime.now()
    if isinstance(d, datetime.datetime):
        return d
    try:
        return pd.to_datetime(d)
    except Exception:
        return datetime.datetime.now()

def cycles_between(keep_date, cycle_type):
    """
    Option A: monthly = 30 days per cycle
    """
    now = datetime.datetime.now()
    keep = parse_date(keep_date)
    delta_days = (now - keep).days
    if cycle_type == "daily":
        return max(delta_days, 0)
    if cycle_type == "weekly":
        return max(delta_days // 7, 0)
    if cycle_type == "monthly":
        return max(delta_days // 30, 0)   # Option A: treat 30 days = 1 month
    return max(delta_days, 0)

def calculate_interest_amount(principal, rate_percent, cycles, interest_type):
    try:
        p = float(principal)
        r = float(rate_percent) / 100.0
        n = float(cycles)
    except Exception:
        return 0.0
    if p <= 0 or r <= 0 or n <= 0:
        return 0.0
    if interest_type == "simple":
        return p * r * n
    if interest_type == "compound":
        return p * ((1 + r) ** n - 1)
    if interest_type == "daily":
        return p * r * n
    return 0.0

# -------------------------
# Auth helpers
# -------------------------
def is_logged_in():
    return st.session_state.get("user") is not None

def show_login():
    st.title("🔐 Sign in")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
        if submitted:
            try:
                user = auth.sign_in_with_email_and_password(email, password)
                st.session_state["user"] = user
                st.success("Signed in")
                st.rerun()
            except Exception as e:
                st.error("Sign-in failed. Check email/password.")
                st.exception(e)
    st.markdown("---")
    st.write("Or register a new owner account below.")
    with st.form("register"):
        remail = st.text_input("Register Email", key="reg_e")
        rpass = st.text_input("Register Password", type="password", key="reg_p")
        rname = st.text_input("Owner Name (optional)", key="reg_n")
        sub = st.form_submit_button("Create Account")
        if sub:
            try:
                auth.create_user_with_email_and_password(remail, rpass)
                st.success("Account created. Please sign in now.")
            except Exception as e:
                st.error("Registration failed.")
                st.exception(e)

def do_logout():
    st.session_state.pop("user", None)
    st.success("Signed out")
    st.rerun()

# -------------------------
# UI / Pages
# -------------------------
st.set_page_config("PADAMRAJ JEWELLERS", layout="wide")
settings_df = get_settings_df()
company_name = settings_df.iloc[0].get("company_name","no")
currency = settings_df.iloc[0].get("currency","₹")

# Header
col1, col2, col3 = st.columns([1,6,1])
with col1:
    if os.path.exists("assets/logo.png"):
        try:
            st.image("assets/logo.png", width=72)
        except Exception:
            pass
with col2:
    st.markdown("<h2 style='text-align:center'>PADAMRAJ JEWELLERS</h2>", unsafe_allow_html=True)

with col3:
    if is_logged_in():
        if st.button("Sign out"):
            do_logout()

# If not logged in show login
if not is_logged_in():
    show_login()
    st.stop()

# After login — load data
customers_df = get_customers_df()
loans_df = get_loans_df()
settings_df = get_settings_df()

# Sidebar clickable menu (buttons)
if "page" not in st.session_state:
    st.session_state["page"] = "dashboard"

st.sidebar.title("Menu")
if st.sidebar.button("Dashboard"):
    st.session_state["page"] = "dashboard"
if st.sidebar.button("Add Customer & Loan"):
    st.session_state["page"] = "add"
if st.sidebar.button("Manage Customers"):
    st.session_state["page"] = "customers"
if st.sidebar.button("Manage Loans"):
    st.session_state["page"] = "loans"
if st.sidebar.button("Export Data"):
    st.session_state["page"] = "export"
if st.sidebar.button("Settings"):
    st.session_state["page"] = "settings"

page = st.session_state.get("page", "dashboard")

# ----------------- Dashboard -----------------
if page == "dashboard":
    st.header("Dashboard")

    # Ensure DataFrames exist and are not empty
    if "loans_df" not in locals() or loans_df is None:
        loans_df = pd.DataFrame()
    if "customers_df" not in locals() or customers_df is None:
        customers_df = pd.DataFrame()

    # Filter active loans safely
    active_loans = (
        loans_df[loans_df.get("claimed", "").astype(str).str.lower() != "yes"]
        if not loans_df.empty else pd.DataFrame()
    )

    total_customers = len(customers_df)
    total_principal = (
        active_loans["principal"].astype(float).sum()
        if not active_loans.empty else 0.0
    )
    total_interest = 0.0
    rows_interest = []

    # Safely loop through loans to calculate interest
    if not active_loans.empty:
        for _, r in active_loans.iterrows():
            cycles = (
                r.get("manual_duration")
                if r.get("manual_duration") not in [None, "", 0]
                else cycles_between(r.get("keep_date"), r.get("cycle_type"))
            )
            interest_amt = calculate_interest_amount(
                r.get("principal", 0),
                r.get("interest_rate", 0),
                cycles,
                r.get("interest_type", "simple"),
            )
            total_interest += interest_amt
            rows_interest.append({
                "loan_id": r.get("_id") or r.get("loan_id"),
                "interest": interest_amt,
                "created_at": r.get("created_at"),
            })

    # Display metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Customers", total_customers)
    c2.metric("Active Principal", f"{total_principal:.2f} {currency}")
    c3.metric("Estimated Interest", f"{total_interest:.2f} {currency}")

    # Display recent interest calculations
    if rows_interest:
        df_int = pd.DataFrame(rows_interest).sort_values("created_at", ascending=False).head(20)
        st.markdown("### Recent Loan Interests")
        st.dataframe(df_int)
    else:
        st.info("No loan interest records found yet.")

    # Bar chart for monthly interest trends
    if not loans_df.empty:
        ldf = loans_df.copy()
        ldf["created_at"] = pd.to_datetime(ldf.get("created_at"), errors="coerce")
        ldf["month"] = ldf["created_at"].dt.to_period("M")

        def loan_calc(r):
            cycles = (
                r.get("manual_duration")
                if r.get("manual_duration") not in [None, "", 0]
                else cycles_between(r.get("keep_date"), r.get("cycle_type"))
            )
            return calculate_interest_amount(
                r.get("principal", 0),
                r.get("interest_rate", 0),
                cycles,
                r.get("interest_type", "simple"),
            )

        ldf["calc_interest"] = ldf.apply(loan_calc, axis=1)
        monthly = ldf.groupby("month")["calc_interest"].sum().fillna(0)

        if not monthly.empty:
            monthly = monthly.sort_index()
            st.markdown("### Monthly Interest (Bar)")
            st.bar_chart(monthly.astype(float))
        else:
            st.info("No data available for monthly interest chart.")
    else:
        st.info("No loans found to display statistics.")

# ----------------- Add Customer & Loan -----------------
elif page == "add":
    st.header("Add Customer")
    with st.form("add_customer"):
        name = st.text_input("Name")
        phone = st.text_input("Phone")
        alt_phone = st.text_input("Alternate Phone")
        aadhaar = st.text_input("Aadhaar Number")
        address = st.text_area("Address")
        notes = st.text_area("Notes")
        sub = st.form_submit_button("Add Customer")
        if sub:
            if not name.strip() or not phone.strip() or not aadhaar.strip():
                st.error("Name, Phone and Aadhaar are mandatory.")
            else:
                payload = {
                    "name": name.strip(), "phone": phone.strip(), "alt_phone": alt_phone.strip(),
                    "aadhaar": aadhaar.strip(), "address": address.strip(), "notes": notes.strip(),
                    "created_at": datetime.datetime.now().isoformat(sep=' ')
                }
                add_customer(payload)
                st.success("Customer added")
                st.rerun()

    st.markdown("---")
    st.header("Add Loan")
    customers_df = get_customers_df()
    cust_names = customers_df["name"].tolist() if not customers_df.empty else []
    with st.form("add_loan"):
        cust = st.selectbox("Customer", [""] + cust_names)
        item = st.text_input("Item / Jewellery Name")
        jtype = st.selectbox("Jewellery Type", ["Gold","Silver","Other"])
        weight = st.text_input("Weight (optional)")
        principal = st.number_input("Principal Amount", min_value=0.0, format="%.2f")
        rate = st.number_input("Interest Rate (%)", min_value=0.0, format="%.2f", value=float(settings_df.iloc[0].get("interest_rate_percent",2.0)))
        itype = st.selectbox("Interest Type", ["simple","compound","daily"])
        cycle = st.selectbox("Cycle Type", ["monthly","weekly","daily"])
        keep_dt = st.date_input("Keep Date", value=datetime.date.today())
        manual_dur = st.number_input("Manual Duration (cycles) - leave 0 for auto", min_value=0.0, format="%.0f", value=0.0)
        sub2 = st.form_submit_button("Add Loan")
        if sub2:
            if not cust:
                st.error("Select a customer")
            elif principal <= 0:
                st.error("Principal must be > 0")
            else:
                cust_row = customers_df[customers_df["name"]==cust].iloc[0]
                payload = {
                    "customer_id": cust_row["_id"],
                    "item_name": item.strip(),
                    "jewellery_type": jtype,
                    "weight": weight.strip(),
                    "principal": float(principal),
                    "interest_rate": float(rate),
                    "interest_type": itype,
                    "cycle_type": cycle,
                    "keep_date": datetime.datetime.combine(keep_dt, datetime.time.min).isoformat(sep=' '),
                    "manual_duration": float(manual_dur) if manual_dur>0 else "",
                    "claimed": "No",
                    "claimed_at": "",
                    "created_at": datetime.datetime.now().isoformat(sep=' ')
                }
                add_loan(payload)
                st.success("Loan added")
                st.rerun()

# ----------------- Manage Customers -----------------
elif page == "customers":
    st.header("Manage Customers")
    customers_df = get_customers_df()
    q = st.text_input("Search by name or aadhaar")
    view = customers_df.copy()
    if q:
        view = view[view["name"].astype(str).str.contains(q, case=False, na=False) | view["aadhaar"].astype(str).str.contains(q, na=False)]
    st.dataframe(view.reset_index(drop=True))
    st.markdown("### Edit / Delete")
    sel = st.selectbox("Select customer", [""] + customers_df["name"].tolist())
    if sel:
        row = customers_df[customers_df["name"]==sel].iloc[0]
        doc_id = row["_id"]
        with st.form("edit_c"):
            nname = st.text_input("Name", value=row.get("name",""))
            nphone = st.text_input("Phone", value=row.get("phone",""))
            nalt = st.text_input("Alt Phone", value=row.get("alt_phone",""))
            naad = st.text_input("Aadhaar", value=row.get("aadhaar",""))
            naddr = st.text_area("Address", value=row.get("address",""))
            nnotes = st.text_area("Notes", value=row.get("notes",""))
            saved = st.form_submit_button("Save")
            if saved:
                update_customer(doc_id, {
                    "name": nname.strip(), "phone": nphone.strip(), "alt_phone": nalt.strip(),
                    "aadhaar": naad.strip(), "address": naddr.strip(), "notes": nnotes.strip()
                })
                st.success("Customer updated")
                st.rerun()
        if st.button("Delete Customer (will delete their loans)"):
            delete_customer(doc_id)
            st.success("Deleted")
            st.rerun()

# ----------------- Manage Loans -----------------
elif page == "loans":
    st.header("Manage Loans")
    loans_df = get_loans_df()
    customers_df = get_customers_df()
    cust_map = {r["_id"]: r["name"] for _, r in customers_df.iterrows()} if not customers_df.empty else {}
    if not loans_df.empty:
        loans_df["customer_name"] = loans_df["customer_id"].map(cust_map)
    q = st.text_input("Search (loan id, item name, customer name)")
    view = loans_df.copy()
    if q:
        view = view[
            view["item_name"].astype(str).str.contains(q, case=False, na=False) |
            view["_id"].astype(str).str.contains(q, case=False, na=False) |
            view["customer_name"].astype(str).str.contains(q, case=False, na=False)
        ]
    # compute due column
    if not view.empty:
        dues = []
        for _, r in view.iterrows():
            cycles = r.get("manual_duration") if r.get("manual_duration") not in [None,"",0,""] else cycles_between(r.get("keep_date"), r.get("cycle_type"))
            interest_amt = calculate_interest_amount(r.get("principal",0), r.get("interest_rate",0), cycles, r.get("interest_type","simple"))
            dues.append(float(r.get("principal",0)) + interest_amt)
        view["total_due"] = dues
    st.dataframe(view.reset_index(drop=True))
    st.markdown("### Select Loan (for Calc / Claim / Edit)")
    sel = st.selectbox("Select loan id", [""] + (loans_df["_id"].tolist() if not loans_df.empty else []))
    if sel:
        loan = loans_df[loans_df["_id"]==sel].iloc[0]
        cust_name = customers_df[customers_df["_id"]==loan["customer_id"]]["name"].iloc[0] if not customers_df.empty else ""
        st.write(f"Loan for: **{cust_name}** — {loan.get('item_name','')}")
        # Manual calculation area
        st.markdown("#### Manual Calculation / Preview")
        with st.form("calc_form"):
            calc_until = st.date_input("Calculate interest until (leave today for current)", value=datetime.date.today())
            # optionally override cycles/rate
            override_rate = st.number_input("Override Interest Rate (%) — leave as recorded to use loan rate", value=float(loan.get("interest_rate",0)))
            override_type = st.selectbox("Interest Type", ["simple","compound","daily"], index=["simple","compound","daily"].index(loan.get("interest_type","simple")))
            override_cycle = st.selectbox("Cycle Type", ["monthly","weekly","daily"], index=["monthly","weekly","daily"].index(loan.get("cycle_type","monthly")))
            submitted_calc = st.form_submit_button("Calculate")
            if submitted_calc:
                # calculate cycles between loan.keep_date and calc_until
                keep_dt = loan.get("keep_date")
                # compute delta days between keep_dt and calc_until
                keep = parse_date(keep_dt)
                end_dt = datetime.datetime.combine(calc_until, datetime.time.min)
                delta_days = (end_dt - keep).days
                if override_cycle == "daily":
                    cycles = max(delta_days, 0)
                elif override_cycle == "weekly":
                    cycles = max(delta_days // 7, 0)
                else: # monthly (Option A uses 30 days)
                    cycles = max(delta_days // 30, 0)
                interest_amt = calculate_interest_amount(loan.get("principal",0), override_rate, cycles, override_type)
                total = float(loan.get("principal",0)) + interest_amt
                st.markdown(f"**Principal:** {loan.get('principal',0):.2f} {currency}")
                st.markdown(f"**Cycles:** {cycles} ({override_cycle})")
                st.markdown(f"**Interest ({override_type} @ {override_rate}%):** {interest_amt:.2f} {currency}")
                st.markdown(f"**Total Payable:** {total:.2f} {currency}")
        # Claim / Edit / Delete
        if str(loan.get("claimed","")).lower() != "yes":
            if st.button("Mark as Claimed / Returned"):
                update_loan(sel, {"claimed":"Yes", "claimed_at": datetime.datetime.now().isoformat(sep=' ')})
                st.success("Marked claimed")
                st.rerun()
        else:
            st.info("This loan was already claimed.")
        st.markdown("Edit loan details")
        with st.form("edit_loan"):
            new_item = st.text_input("Item name", value=loan.get("item_name",""))
            new_pr = st.number_input("Principal", value=float(loan.get("principal",0)))
            new_rate = st.number_input("Interest Rate (%)", value=float(loan.get("interest_rate",0)))
            new_type = st.selectbox("Interest Type", ["simple","compound","daily"], index=["simple","compound","daily"].index(loan.get("interest_type","simple")))
            new_cycle = st.selectbox("Cycle Type", ["monthly","weekly","daily"], index=["monthly","weekly","daily"].index(loan.get("cycle_type","monthly")))
            new_manual = st.number_input("Manual Duration (cycles)", value=float(loan.get("manual_duration") if loan.get("manual_duration") not in [None,""] else 0.0))
            saved = st.form_submit_button("Save Loan")
            if saved:
                update_loan(sel, {
                    "item_name": new_item.strip(), "principal": float(new_pr),
                    "interest_rate": float(new_rate), "interest_type": new_type,
                    "cycle_type": new_cycle, "manual_duration": float(new_manual) if new_manual>0 else ""
                })
                st.success("Loan updated")
                st.rerun()
        if st.button("Delete Loan"):
            delete_loan(sel)
            st.success("Loan deleted")
            st.rerun()

# ----------------- Export -----------------
elif page == "export":
    st.header("Export / Backup")
    customers_df = get_customers_df()
    loans_df = get_loans_df()
    settings_df = get_settings_df()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        customers_df.to_excel(writer, sheet_name="customers", index=False)
        loans_df.to_excel(writer, sheet_name="loan", index=False)
        settings_df.to_excel(writer, sheet_name="settings", index=False)
    data = buf.getvalue()
    st.download_button("Download Excel backup", data=data, file_name=EXPORT_NAME, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if st.button("Refresh data"):
        st.rerun()

# ----------------- Settings -----------------
elif page == "settings":
    st.header("Settings")
    settings_df = get_settings_df()
    company = st.text_input("Company name", value=settings_df.iloc[0].get("company_name","PADAMRAJ JEWELLERS"))
    curr = st.text_input("Currency symbol", value=settings_df.iloc[0].get("currency","₹"))
    cycle_days = st.number_input("Interest cycle days (used as default)", value=int(settings_df.iloc[0].get("interest_cycle_days",30)))
    default_rate = st.number_input("Default interest rate (%)", value=float(settings_df.iloc[0].get("interest_rate_percent",2.0)))
    if st.button("Save settings"):
        docs = list(db.collection("settings").limit(1).stream())
        payload = {"company_name": company, "currency": curr, "interest_cycle_days": int(cycle_days), "interest_rate_percent": float(default_rate)}
        if docs:
            db.collection("settings").document(docs[0].id).set(payload)
        else:
            db.collection("settings").add(payload)
        st.success("Settings saved")
        st.rerun()
