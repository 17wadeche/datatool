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
    # 3) Classify Well Understood vs Not Well Understood (row-level)
    # -----------------------------------------------------
    # Count distinct RFR codes per PE - PLI #
    pli_rfr_counts = (
        df.groupby("PE - PLI #")["RFR Codes"]
        .nunique()
        .rename("num_distinct_rfr")
    )

    # RFR frequency across entire dataset
    rfr_freq = df["RFR Codes"].value_counts().to_dict()

    # Merge back
    df = df.merge(pli_rfr_counts, on="PE - PLI #", how="left")

    def classify_well_understood(row):
        """Row-level classification based on RFR logic."""
        if row["num_distinct_rfr"] > 1:
            return "Not Well Understood"
        else:
            freq = rfr_freq.get(row["RFR Codes"], 0)
            return "Well Understood" if freq >= 50 else "Not Well Understood"

    df["KnowledgeClass"] = df.apply(classify_well_understood, axis=1)

    # -----------------------------------------------------
    # 3A) Force entire Product Event to "Not Well Understood" 
    #     if *any* row within that PE - PLI # is Not Well Understood
    # -----------------------------------------------------
    df["KnowledgeClass"] = df.groupby("PE - PLI #")["KnowledgeClass"].transform(
        lambda group: "Not Well Understood" 
                      if "Not Well Understood" in group.values 
                      else "Well Understood"
    )

    # -----------------------------------------------------
    # 4) Region & FDA checks
    # -----------------------------------------------------
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
        # Strictly checks for "US FDA - MDR: Malfunction - Reportable"
        return "US FDA - MDR: MALFUNCTION - REPORTABLE" in str(reportability_text).upper()

    # -----------------------------------------------------
    # 5) Workflow classification function
    # -----------------------------------------------------
    def classify_workflow(row):
        country = str(row.get("Country – PE", "")).strip().title()
        knowledge = row.get("KnowledgeClass", "")
        rep_text = str(row.get("Reportability", "")).upper()

        us_terr = is_us_territory(country)
        eu = is_eu(country)
        canada = is_canada(country)
        japan = is_japan(country)
        gchina = is_greater_china(country)

        fda_rep = is_fda_reportable(rep_text)

        # Workflow 1: US territory, NOT FDA Reportable, Well Understood
        if us_terr and (not fda_rep) and (knowledge == "Well Understood"):
            return 1

        # Workflow 2: (US FDA Reportable) OR (EU) OR (Canada), AND Well Understood
        if knowledge == "Well Understood":
            if (us_terr and fda_rep) or eu or canada:
                return 2

        # Workflow 3: US, EU, Canada (any reportability), Not Well Understood
        if (us_terr or eu or canada) and (knowledge == "Not Well Understood"):
            return 3

        # Workflow 4: OUS-other (not US, not EU, not Canada, not Japan, not G. China)
        is_ous_other = (
            (not us_terr) and
            (not eu) and
            (not canada) and
            (not japan) and
            (not gchina)
        )
        if is_ous_other:
            return 4

        # Workflow 5: Japan & Greater China
        if japan or gchina:
            return 5

        # If none matched, return 0
        return 0

    df["Workflow"] = df.apply(classify_workflow, axis=1)

    # -----------------------------------------------------
    # 6) Prepare GFE at the Product Event level
    # -----------------------------------------------------
    # If ANY row in a given PE - PLI # is GFE, treat that entire PE as GFE
    # for counting distinct product events.
    any_gfe_by_pe = (
        df.groupby("PE - PLI #")["IsGFE"]
        .any()  # True if at least one row is True
        .rename("Any_GFE")
        .reset_index()
    )
    df = df.merge(any_gfe_by_pe, on="PE - PLI #", how="left")

    # -----------------------------------------------------
    # 7) Summaries (Distinct Product Event ID basis)
    # -----------------------------------------------------
    # We drop duplicates so each PE - PLI # is counted only once
    df_pe = df.drop_duplicates(subset=["PE - PLI #"]).copy()

    # Summarize at the product-event level
    summary_pe = (
        df_pe.groupby(["Workflow", "TeamFile", "Source System – PE"])
        .agg(
            Distinct_Product_Events=("PE - PLI #", "count"),
            GFE_Events=("Any_GFE", "sum")  # sum of booleans => count of True
        )
        .reset_index()
    )

    st.write("### Distinct PE - PLI # Summary by Workflow & Team (Filename)")
    st.dataframe(summary_pe)

    # Download button for the product-event summary
    csv_data_pe = summary_pe.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Distinct Product Event Summary",
        data=csv_data_pe,
        file_name="workflow_summary_by_event_id.csv",
        mime="text/csv"
    )

    # -----------------------------------------------------
    # (Optional) Row-level summary as before
    # -----------------------------------------------------
    # If you still want to see row-level volumes, leave this block:
    row_summary = (
        df.groupby(["Workflow", "TeamFile", "Source System – PE"])
        .agg(
            GFE_Count=("IsGFE", "sum"),
            Total_Rows=("IsGFE", "count")
        )
        .reset_index()
    )

    st.write("### Row-Level GFE Summary by Workflow & Team (Filename)")
    st.dataframe(row_summary)

    csv_data_row = row_summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Row-Level GFE Summary",
        data=csv_data_row,
        file_name="workflow_row_level_summary.csv",
        mime="text/csv"
    )

    # -----------------------------------------------------
    # (Optional) Show the full classified DataFrame by File
    # -----------------------------------------------------
    with st.expander("See Full Classified Data (by File)"):
        for team_name in df["TeamFile"].unique():
            st.write(f"### Classified Data from: {team_name}")
            subset_df = df[df["TeamFile"] == team_name].copy()
            st.dataframe(subset_df)

            csv_data = subset_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"Download '{team_name}' Full Classified Data",
                data=csv_data,
                file_name=f"{team_name}_classified.csv",
                mime="text/csv"
            )
