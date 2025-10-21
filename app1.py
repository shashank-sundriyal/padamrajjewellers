import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import datetime
import streamlit as st
st.write(st.secrets)

import streamlit as st

st.write("✅ App started")
st.write("Secrets keys:", list(st.secrets.keys()))


creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"])
client = gspread.authorize(creds)

sheet = client.open_by_key(st.secrets["gsheet_id"])

# -----------------------------
# Google Sheets Setup
# -----------------------------
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"])
client = gspread.authorize(creds)

# Open your sheet
sheet = client.open_by_key(st.secrets["gsheet_id"])
customers_ws = sheet.worksheet("customers")
loan_ws = sheet.worksheet("loan")
settings_ws = sheet.worksheet("settings")

# Load data into DataFrames
df_customers = get_as_dataframe(customers_ws).fillna("")
df_loan = get_as_dataframe(loan_ws).fillna("")
df_settings = get_as_dataframe(settings_ws).fillna("")

# Extract settings
company_name = df_settings.loc[0, "company_name"] if "company_name" in df_settings.columns else "My Jewellery Shop"
currency = df_settings.loc[0, "currency"] if "currency" in df_settings.columns else "₹"
default_cycle = df_settings.loc[0, "default_cycle"] if "default_cycle" in df_settings.columns else "monthly"

# -----------------------------
# Helper Functions
# -----------------------------
def parse_datetime_flexible(s):
    if not s:
        return datetime.datetime.now()
    formats = ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(s, fmt)
        except:
            continue
    return datetime.datetime.now()

def calculate_cycles(keep_date_str, cycle_type):
    keep_date = parse_datetime_flexible(keep_date_str)
    delta_days = (datetime.datetime.now() - keep_date).days
    if cycle_type.lower() == "daily":
        return delta_days
    elif cycle_type.lower() == "weekly":
        return delta_days // 7
    elif cycle_type.lower() == "monthly":
        return delta_days // 30
    return 0

def calculate_interest(principal, rate, cycles, interest_type="simple"):
    if interest_type.lower() == "simple":
        return principal * (rate / 100) * cycles
    elif interest_type.lower() == "compound":
        return principal * ((1 + rate / 100) ** cycles - 1)
    return 0

# -----------------------------
# Streamlit UI
# -----------------------------
st.title(f"{company_name} Loan Management")
st.sidebar.header("Settings")
st.sidebar.write(f"Currency: {currency}")
st.sidebar.write(f"Default Cycle: {default_cycle}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Add Customer", "Add Loan", "Amount Due", "Claim Jewellery", "Customer List & Summary"])

# -----------------------------
# Tab 1: Add Customer
# -----------------------------
with tab1:
    st.subheader("Add Customer")
    with st.form("customer_form"):
        name = st.text_input("Name")
        address = st.text_input("Address")
        contact = st.text_input("Contact")
        alt_contact = st.text_input("Alternate Contact")
        aadhar = st.text_input("Aadhar Number")
        submitted = st.form_submit_button("Add Customer")
        if submitted:
            if not name or not address or not contact or not aadhar:
                st.error("Name, Address, Contact, and Aadhar are mandatory!")
            elif name in df_customers.get("Name", []).values:
                st.info("Customer already exists!")
            else:
                new_customer = {"Name": name, "Address": address, "Contact": contact,
                                "Alternate Contact": alt_contact, "Aadhar Number": aadhar}
                df_customers = df_customers.append(new_customer, ignore_index=True)
                set_with_dataframe(customers_ws, df_customers)
                st.success(f"Customer '{name}' added successfully!")

# -----------------------------
# Tab 2: Add Loan
# -----------------------------
with tab2:
    st.subheader("Add Loan")
    with st.form("loan_form"):
        customer = st.selectbox("Select Customer", df_customers.get("Name", []))
        jewellery_name = st.text_input("Jewellery Name")
        jewellery_type = st.selectbox("Jewellery Type", ["Gold", "Silver", "Other"])
        amount = st.number_input("Loan Amount", min_value=0.0)
        interest_rate = st.number_input("Interest Rate (%)", min_value=0.0)
        interest_type = st.selectbox("Interest Type", ["simple", "compound"])
        cycle_type = st.selectbox("Cycle Type", ["daily", "weekly", "monthly"])
        keep_date = st.date_input("Keep Date")
        submitted = st.form_submit_button("Add Loan")
        if submitted:
            keep_date_str = keep_date.strftime("%Y-%m-%d")
            new_loan = {"Customer": customer, "Jewellery Name": jewellery_name, "Type": jewellery_type,
                        "Amount": amount, "Interest Rate": interest_rate, "Interest Type": interest_type,
                        "Cycle": cycle_type, "Keep Date": keep_date_str, "Claimed": "No"}
            df_loan = df_loan.append(new_loan, ignore_index=True)
            set_with_dataframe(loan_ws, df_loan)
            st.success(f"Loan added for customer '{customer}'")

# -----------------------------
# Tab 3: Calculate Amount Due
# -----------------------------
with tab3:
    st.subheader("Calculate Amount Due")
    customer_due = st.selectbox("Select Customer", df_customers.get("Name", []), key="due_select")
    if st.button("Show Amount Due"):
        loans = df_loan[(df_loan["Customer"] == customer_due) & (df_loan["Claimed"] == "No")]
        if loans.empty:
            st.info("No active loans for this customer.")
        else:
            total = 0
            for idx, row in loans.iterrows():
                cycles = calculate_cycles(row["Keep Date"], row["Cycle"])
                interest = calculate_interest(row["Amount"], row["Interest Rate"], cycles, row["Interest Type"])
                total_due = row["Amount"] + interest
                total += total_due
                st.write(f"{row['Jewellery Name']} ({row['Type']}): Principal {row['Amount']} + Interest {interest:.2f} = Total Due {total_due:.2f}")
            st.write(f"**Total Amount Due:** {total:.2f}")

# -----------------------------
# Tab 4: Claim Jewellery
# -----------------------------
with tab4:
    st.subheader("Claim Jewellery")
    customer_claim = st.selectbox("Select Customer", df_customers.get("Name", []), key="claim_select")
    loans = df_loan[(df_loan["Customer"] == customer_claim) & (df_loan["Claimed"] == "No")]
    if not loans.empty:
        st.write("Active Loans:")
        for idx, row in loans.iterrows():
            st.write(f"{idx+1}. {row['Jewellery Name']} ({row['Type']}) - Amount: {row['Amount']}")
        item_no = st.number_input("Enter Item Number to Claim", min_value=1, max_value=len(loans), step=1)
        if st.button("Claim Selected Item"):
            loan_index = loans.index[item_no - 1]
            df_loan.at[loan_index, "Claimed"] = "Yes"
            set_with_dataframe(loan_ws, df_loan)
            st.success(f"{df_loan.at[loan_index, 'Jewellery Name']} marked as claimed.")
    else:
        st.info("No active loans to claim.")

# -----------------------------
# Tab 5: Customer List & Summary
# -----------------------------
with tab5:
    st.subheader("Customer List")
    st.dataframe(df_loan)

    st.subheader("Customer Summary")
    summary = []
    for cust in df_customers.get("Name", []):
        loans = df_loan[(df_loan["Customer"] == cust) & (df_loan["Claimed"] == "No")]
        total_principal = loans["Amount"].sum()
        total_interest = sum([calculate_interest(row["Amount"], row["Interest Rate"],
                                                 calculate_cycles(row["Keep Date"], row["Cycle"]),
                                                 row["Interest Type"]) for idx, row in loans.iterrows()])
        summary.append({"Customer": cust, "Total Principal": total_principal,
                        "Total Interest": total_interest, "Total Outstanding": total_principal + total_interest})
    df_summary = pd.DataFrame(summary)
    st.dataframe(df_summary)

    # Export CSV buttons
    if st.button("Export Customer List to CSV"):
        df_loan.to_csv("customer_loans.csv", index=False)
        st.success("Customer loans exported to customer_loans.csv")
    if st.button("Export Summary to CSV"):
        df_summary.to_csv("customer_summary.csv", index=False)
        st.success("Customer summary exported to customer_summary.csv")
