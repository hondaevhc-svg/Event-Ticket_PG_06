import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import os

st.set_page_config(page_title="🎟️ Event Management System", layout="wide")

# --- CUSTOM CSS FOR CENTERING ---
st.markdown("""
    <style>
    [data-testid="stDataFrame"] div[data-testid="stTable"] {
        text-align: center !important;
    }
    th { text-align: center !important; }
    </style>
    """, unsafe_allow_html=True)

# --- SESSION STATE MANAGEMENT ---
if 'admin_pass_key' not in st.session_state:
    st.session_state.admin_pass_key = ""
if 'menu_pass_key' not in st.session_state:
    st.session_state.menu_pass_key = ""

# --- DATABASE CONNECTION ---
def get_engine():
    db_url = st.secrets["connections"]["postgresql"]["url"]
    return create_engine(db_url)

@st.cache_data(ttl=60)
def load_all_data():
    engine = get_engine()
    try:
        tickets_df = pd.read_sql("SELECT * FROM tickets", engine)
        menu_df = pd.read_sql("SELECT * FROM menu", engine)

        # Cleaning & NULL handling
        tickets_df['Visitor_Seats'] = tickets_df['Visitor_Seats'].fillna(0)
        tickets_df['Sold'] = tickets_df['Sold'].fillna(False).astype(bool)
        tickets_df['Visited'] = tickets_df['Visited'].fillna(False).astype(bool)
        tickets_df['Customer'] = tickets_df['Customer'].fillna("")
        tickets_df['Admit'] = pd.to_numeric(tickets_df['Admit'], errors='coerce').fillna(1)
        tickets_df['Seq'] = pd.to_numeric(tickets_df['Seq'], errors='coerce')
        tickets_df['TicketID'] = tickets_df['TicketID'].astype(str).str.zfill(4)

        return tickets_df, menu_df
    except Exception as e:
        st.error(f"Database Error: {e}")
        st.stop()

def save_to_db(tickets_df, menu_df=None):
    engine = get_engine()
    tickets_df.to_sql("tickets", engine, if_exists="replace", index=False)
    if menu_df is not None:
        menu_df.to_sql("menu", engine, if_exists="replace", index=False)
    st.cache_data.clear()

def custom_sort(df):
    if 'Seq' not in df.columns: return df
    return df.assign(sort_key=df['Seq'].apply(lambda x: 10 if x == 0 or x == '0' else int(x))).sort_values(
        'sort_key').drop(columns='sort_key')

# Initial Load
tickets, menu = load_all_data()

# --- SIDEBAR ---
with st.sidebar:
    st.header("Admin Settings")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    admin_pass = st.text_input("Reset Database Password", type="password", key="admin_pass_input")
    if st.button("🚨 Reset Database"):
        if admin_pass == "admin123":
            tickets['Sold'] = False
            tickets['Visited'] = False
            tickets['Customer'] = ""
            tickets['Visitor_Seats'] = 0
            tickets['Timestamp'] = None
            save_to_db(tickets)
            st.rerun()
        else:
            st.error("Incorrect Admin Password")

tabs = ["📊 Dashboard", "💰 Sales", "🚶 Visitors", "⚙️ Edit Menu"]
tab_selection = st.tabs(tabs)

# 1. DASHBOARD
with tab_selection[0]:
    st.subheader("Inventory & Visitor Analytics")
    df = tickets.copy()

    summary = df.groupby(['Seq', 'Type', 'Category', 'Admit']).agg(
        Total_Tickets=('TicketID', 'count'),
        Tickets_Sold=('Sold', 'sum'),
        Total_Visitors=('Visitor_Seats', 'sum')
    ).reset_index()

    summary['Total_Seats'] = summary['Total_Tickets'] * summary['Admit']
    summary['Seats_sold'] = summary['Tickets_Sold'] * summary['Admit']
    summary['Balance_Tickets'] = summary['Total_Tickets'] - summary['Tickets_Sold']
    summary['Balance_Seats'] = summary['Total_Seats'] - summary['Seats_sold']
    summary['Balance_Visitors'] = summary['Seats_sold'] - summary['Total_Visitors']

    column_order = ['Seq', 'Type', 'Category', 'Admit', 'Total_Tickets', 'Tickets_Sold',
                    'Total_Seats', 'Seats_sold', 'Total_Visitors', 'Balance_Tickets',
                    'Balance_Seats', 'Balance_Visitors']

    summary = custom_sort(summary[column_order])
    totals = pd.DataFrame([summary.select_dtypes(include='number').sum()])
    totals['Seq'] = 'Total'

    summary_final = pd.concat([summary, totals], ignore_index=True).dropna(how='all')

    # FIX: Changed height=None to height="auto"
    st.dataframe(summary_final, hide_index=True, use_container_width=True, height="auto")

# 2. SALES
with tab_selection[1]:
    st.subheader("Sales Management")
    col_in, col_out = st.columns([1, 1.2])

    with col_in:
        sale_tab = st.radio("Action", ["Manual", "Bulk Upload", "Reverse Sale"], horizontal=True)
        if sale_tab == "Manual":
            s_type = st.radio("Type", ["Public", "Guest"], horizontal=True)
            s_cat = st.selectbox("Category", menu[menu['Type'] == s_type]['Category'])
            avail = tickets[(tickets['Type'] == s_type) & (tickets['Category'] == s_cat) & (~tickets['Sold'])]['TicketID'].tolist()
            if avail:
                with st.form("sale_form", clear_on_submit=True):
                    tid = st.selectbox("Ticket ID", avail)
                    cust = st.text_input("Customer Name")
                    if st.form_submit_button("Confirm Sale"):
                        idx = tickets.index[tickets['TicketID'] == tid][0]
                        tickets.at[idx, 'Sold'] = True
                        tickets.at[idx, 'Customer'] = cust
                        tickets.at[idx, 'Timestamp'] = str(pd.Timestamp.now())
                        save_to_db(tickets)
                        st.rerun()

        elif sale_tab == "Bulk Upload":
            uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])
            if uploaded_file and st.button("Process Bulk Sale"):
                up_df = pd.read_excel(uploaded_file)
                up_df['TicketID'] = up_df['TicketID'].astype(str).str.zfill(4)
                for _, row in up_df.iterrows():
                    match = tickets[(tickets['TicketID'] == row['TicketID']) & (~tickets['Sold'])]
                    if not match.empty:
                        idx = match.index[0]
                        tickets.at[idx, 'Sold'] = True
                        tickets.at[idx, 'Customer'] = row['CustomerName']
                        tickets.at[idx, 'Timestamp'] = str(pd.Timestamp.now())
                save_to_db(tickets)
                st.rerun()

        elif sale_tab == "Reverse Sale":
            sold_list = tickets[tickets['Sold']]['TicketID'].tolist()
            if sold_list:
                with st.form("reverse_sale"):
                    rev_tid = st.selectbox("Select Ticket to Undo", sold_list)
                    if st.form_submit_button("Reverse Sale"):
                        idx = tickets.index[tickets['TicketID'] == rev_tid][0]
                        tickets.at[idx, 'Sold'] = False
                        tickets.at[idx, 'Customer'] = ""
                        tickets.at[idx, 'Timestamp'] = None
                        save_to_db(tickets)
                        st.rerun()

    with col_out:
        st.write("**Recent Sales History**")
        recent_sales = tickets[tickets['Sold']].sort_values('Timestamp', ascending=False).copy()
        if not recent_sales.empty:
            recent_sales.insert(0, 'Sno', range(1, len(recent_sales) + 1))
            st.dataframe(recent_sales[['Sno', 'TicketID', 'Category', 'Customer', 'Timestamp']], hide_index=True,
                         use_container_width=True)

# 3. VISITORS
with tab_selection[2]:
    st.subheader("Visitor Entry Management")
    v_in, v_out = st.columns([1, 1.2])

    with v_in:
        v_action = st.radio("Action", ["Entry", "Reverse Entry"], horizontal=True)
        if v_action == "Entry":
            v_type = st.radio("Entry Type", ["Public", "Guest"], horizontal=True, key="v_type_radio")
            v_cat = st.selectbox("Entry Category", menu[menu['Type'] == v_type]['Category'], key="v_cat_sel")
            elig = tickets[(tickets['Type'] == v_type) & (tickets['Category'] == v_cat) & (tickets['Sold']) & (
                ~tickets['Visited'])]['TicketID'].tolist()
            if elig:
                with st.form("checkin"):
                    tid = st.selectbox("Select Ticket ID", elig)
                    max_v = int(tickets[tickets['TicketID'] == tid]['Admit'].values[0])
                    v_count = st.number_input("Confirmed Visitors", 1, max_v, max_v)
                    if st.form_submit_button("Confirm Entry"):
                        idx = tickets.index[tickets['TicketID'] == tid][0]
                        tickets.at[idx, 'Visited'] = True
                        tickets.at[idx, 'Visitor_Seats'] = v_count
                        tickets.at[idx, 'Timestamp'] = str(pd.Timestamp.now())
                        save_to_db(tickets)
                        st.rerun()

        elif v_action == "Reverse Entry":
            visited_list = tickets[tickets['Visited']]['TicketID'].tolist()
            if visited_list:
                with st.form("reverse_visitor"):
                    rev_v_tid = st.selectbox("Select Ticket to Undo Entry", visited_list)
                    if st.form_submit_button("Reverse Entry"):
                        idx = tickets.index[tickets['TicketID'] == rev_v_tid][0]
                        tickets.at[idx, 'Visited'] = False
                        tickets.at[idx, 'Visitor_Seats'] = 0
                        save_to_db(tickets)
                        st.rerun()

    with v_out:
        st.write("**Recent Visitor Entries**")
        recent_visitors = tickets[tickets['Visited']].sort_values('Timestamp', ascending=False).copy()
        if not recent_visitors.empty:
            recent_visitors.insert(0, 'Sno', range(1, len(recent_visitors) + 1))
            st.dataframe(recent_visitors[['Sno', 'TicketID', 'Category', 'Visitor_Seats', 'Customer', 'Timestamp']],
                         hide_index=True, use_container_width=True)

# 4. EDIT MENU
with tab_selection[3]:
    st.subheader("Menu & Series Configuration")
    menu_display = custom_sort(menu.copy())
    edited_menu = st.data_editor(menu_display, hide_index=True, use_container_width=True)

    # UPDATED LOGIC: Recalculate on-the-fly for any row in the editor
    for index, row in edited_menu.iterrows():
        try:
            if '-' in str(row['Series']):
                start, end = map(int, str(row['Series']).split('-'))
                count = (end - start) + 1
                edited_menu.at[index, 'Alloc'] = count
                edited_menu.at[index, 'Total_Capacity'] = count * row['Admit']
        except:
            pass

    menu_pass = st.text_input("Enter Menu Update Password", type="password", key="menu_pass_input")
    if st.button("Update Database Menu"):
        if menu_pass == "admin123":
            save_to_db(tickets, edited_menu)
            st.success("Menu Synchronized!")
            st.rerun() # This will clear the password field automatically
        else:
            st.error("Incorrect Menu Password")
