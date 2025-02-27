import streamlit as st
import pandas as pd

st.title("GFE Volumes & Workflow Classifier")

########################################
# 1) Upload multiple Excel files
########################################
uploaded_files = st.file_uploader(
    "Upload Excel files (one per team). Each must have a 'Report 1' tab.",
    type=["xlsx", "xls"],
    accept_multiple_files=True
)

if uploaded_files:
    # List to hold all data from 'Report 1' across files
    df_list = []

    for file in uploaded_files:
        xls = pd.ExcelFile(file)
        # Check if 'Report 1' exists
        if "Report 1" not in xls.sheet_names:
            st.warning(f"File '{file.name}' has no 'Report 1' sheet. Skipping.")
            continue

        # Read data from 'Report 1'
        temp_df = pd.read_excel(xls, sheet_name="Report 1")

        # Tag rows with the file name (so we know which team it belongs to)
        temp_df["TeamFile"] = file.name

        df_list.append(temp_df)

    if not df_list:
        st.error("No valid 'Report 1' data found across files. Please check again.")
        st.stop()

    # Combine all 'Report 1' data into a single DataFrame
    df = pd.concat(df_list, ignore_index=True)

    st.write("### Raw Data from All Teams (Report 1 tabs combined)")
    st.dataframe(df)

    # -----------------------------------------------------
    # 2) Flag GFE rows
    # -----------------------------------------------------
    gfe_keywords = ["Follow-up for Prod/Info", "Follow Up for Information"]
    df["IsGFE"] = df["Communication"].apply(
        lambda val: any(k in str(val) for k in gfe_keywords)
    )

    # -----------------------------------------------------
    # 3) Classify Well Understood vs Not Well Understood
    # -----------------------------------------------------
    # Distinct RFR per PLI
    pli_rfr_counts = (
        df.groupby("PE PLI #")["RFR Codes"]
        .nunique()
        .rename("num_distinct_rfr")
    )
    # RFR frequency across entire dataset
    rfr_freq = df["RFR Codes"].value_counts().to_dict()

    # Merge back
    df = df.merge(pli_rfr_counts, on="PE PLI #", how="left")

    def classify_well_understood(row):
        if row["num_distinct_rfr"] > 1:
            return "Not Well Understood"
        else:
            freq = rfr_freq.get(row["RFR Codes"], 0)
            return "Well Understood" if freq >= 50 else "Not Well Understood"

    df["KnowledgeClass"] = df.apply(classify_well_understood, axis=1)

    # -----------------------------------------------------
    # 4) Region & FDA checks
    # -----------------------------------------------------
    # We'll define sets for EU, Greater China, etc. 
    # (You can adapt these lists as needed.)
    
    eu_countries = {
        "Austria", "Belgium", "Croatia", "Cyprus", "Czech Republic",
        "Denmark", "Finland", "France", "Germany", "Greece", "Hungary",
        "Ireland", "Italy", "Luxembourg", "Netherlands", "Poland",
        "Portugal", "Slovakia", "Spain", "Sweden"
    }
    
    greater_china_countries = {
        "China", "Hong Kong", "Macao", "Taiwan", "Viet Nam"
    }
    
    def is_us_territory(country):
        # We only see "United States" in your list for US. 
        # If you also handle "Guam" or "Puerto Rico," add them here.
        return country.strip().title() == "United States"

    def is_eu(country):
        return country.strip().title() in eu_countries

    def is_canada(country):
        return country.strip().title() == "Canada"

    def is_japan(country):
        return country.strip().title() == "Japan"

    def is_greater_china(country):
        return country.strip().title() in greater_china_countries

    def is_fda_reportable(reportability_text):
        # Strictly checks for the phrase "US FDA - MDR: Malfunction - Reportable"
        return "US FDA - MDR: Malfunction - Reportable".upper() in str(reportability_text).upper()

    # -----------------------------------------------------
    # 5) Workflow classification function
    # -----------------------------------------------------
    def classify_workflow(row):
        country = str(row.get("Country – PE", "")).strip().title()
        knowledge = row.get("KnowledgeClass", "")
        rep_text = str(row.get("Reportability", "")).upper()

        # Region checks
        us_terr = is_us_territory(country)
        eu = is_eu(country)
        canada = is_canada(country)
        japan = is_japan(country)
        gchina = is_greater_china(country)
        
        # If it's not in US, not in EU, not in Canada, not in Japan, not in G. China
        # we'll call it OUS-other
        # (But see below for the workflow logic.)
        
        # FDA check
        fda_rep = is_fda_reportable(rep_text)

        # Workflow 1:
        #   US territory, NOT FDA Reportable, Well Understood
        if us_terr and (not fda_rep) and (knowledge == "Well Understood"):
            return 1

        # Workflow 2:
        #   (US FDA Reportable) OR (EU) OR (Canada)
        #   AND Well Understood
        if knowledge == "Well Understood":
            if (us_terr and fda_rep) or (eu) or (canada):
                return 2

        # Workflow 3:
        #   US, EU, Canada (any reportability)
        #   Not Well Understood
        if (us_terr or eu or canada) and (knowledge == "Not Well Understood"):
            return 3

        # Workflow 4:
        #   OUS (minus EU, Canada, Japan, Greater China)
        #   => if not US, not EU, not Canada, not Japan, not G.China
        #   Show Well vs. Not Well Understood separately
        is_ous_other = (
            (not us_terr) and
            (not eu) and
            (not canada) and
            (not japan) and
            (not gchina)
        )
        if is_ous_other:
            return 4

        # Workflow 5:
        #   Japan & Greater China
        if japan or gchina:
            return 5

        # If none matched, return 0
        return 0

    df["Workflow"] = df.apply(classify_workflow, axis=1)

    # -----------------------------------------------------
    # 6) Summaries (GFE volumes by Workflow & Team)
    # -----------------------------------------------------
    summary = (
        df.groupby(["Workflow", "TeamFile"])
        .agg(
            GFE_Count=("IsGFE", "sum"),
            Total_Rows=("IsGFE", "count")
        )
        .reset_index()
    )

    st.write("### GFE Summary by Workflow & Team (Filename)")
    st.dataframe(summary)

    # Download button for the summary
    csv_data = summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Workflow GFE Summary",
        data=csv_data,
        file_name="workflow_gfe_summary.csv",
        mime="text/csv"
    )

    # Optionally show the full classified DataFrame
    with st.expander("See Full Classified Data"):
        st.dataframe(df)
