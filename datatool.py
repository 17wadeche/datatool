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

    st.write("### 1) Raw Data from All Teams (Report 1 tabs combined)")
    st.dataframe(df)

    # -----------------------------------------------------
    # 2) Flag GFE rows (row-level)
    # -----------------------------------------------------
    gfe_keywords = ["Follow-up for Prod/Info", "Follow Up for Information"]
    df["IsGFE"] = df["Communication"].apply(
        lambda val: any(k in str(val) for k in gfe_keywords)
    )

    # -----------------------------------------------------
    # 3) Row-level classification: Well Understood vs Not Well Understood
    #    grouped by "Product Event ID"
    # -----------------------------------------------------

    # 3A) Count distinct RFR codes per Product Event
    rfr_count_by_pe = (
        df.groupby("Product Event ID")["RFR Codes"]
        .nunique()
        .rename("num_distinct_rfr")
    )

    # 3B) Frequency of each RFR code across the entire dataset
    rfr_freq = df["RFR Codes"].value_counts().to_dict()

    # 3C) Merge the distinct RFR counts back to df
    df = df.merge(rfr_count_by_pe, on="Product Event ID", how="left")

    # 3D) Row-level classification based on your logic
    def preliminary_knowledge_class(row):
        if row["num_distinct_rfr"] > 1:
            return "Not Well Understood"
        else:
            freq = rfr_freq.get(row["RFR Codes"], 0)
            return "Well Understood" if freq >= 50 else "Not Well Understood"

    df["KnowledgeClass"] = df.apply(preliminary_knowledge_class, axis=1)

    # -----------------------------------------------------
    # 3E) PE-level override:
    #     If ANY row in the same Product Event ID is Not Well Understood,
    #     make them ALL Not Well Understood for that PE
    # -----------------------------------------------------
    df["PE level KnowledgeClass"] = df.groupby("Product Event ID")["KnowledgeClass"].transform(
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
    # 5) PE-level Workflow
    #    => classify based on "PE level KnowledgeClass"
    # -----------------------------------------------------
    def classify_pe_workflow(row):
        # We read the region/fda logic from the row
        # but use the *PE-level* knowledge class
        country = str(row.get("Country – PE", "")).strip().title()
        knowledge = row.get("PE level KnowledgeClass", "")  # from group override
        rep_text = str(row.get("Reportability", "")).upper()

        # Region checks
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

        # Workflow 3: US/EU/Canada (any reportability), Not Well Understood
        if (us_terr or eu or canada) and (knowledge == "Not Well Understood"):
            return 3

        # Workflow 4: OUS-other => not US/EU/Canada/Japan/Greater China
        is_ous_other = (
            (not us_terr)
            and (not eu)
            and (not canada)
            and (not japan)
            and (not gchina)
        )
        if is_ous_other:
            return 4

        # Workflow 5: Japan & Greater China
        if japan or gchina:
            return 5

        # If none matched
        return 0

    df["PE level Workflow"] = df.apply(classify_pe_workflow, axis=1)

    # -----------------------------------------------------
    # 6) PE-level GFE
    #    => if ANY row in the same Product Event ID is GFE,
    #       treat entire PE as GFE
    # -----------------------------------------------------
    df["PE level GFE"] = df.groupby("Product Event ID")["IsGFE"].transform(any)

    # -----------------------------------------------------
    # 7) Summaries at the Product Event ID level
    # -----------------------------------------------------
    # 7A) Drop duplicates so each Product Event ID only appears once
    df_pe = df.drop_duplicates(subset=["Product Event ID"]).copy()

    # 7B) Summarize by PE-level workflow, TeamFile, etc.
    summary_pe = (
        df_pe.groupby(["PE level Workflow", "TeamFile", "Source System – PE"])
        .agg(
            Distinct_Product_Events=("Product Event ID", "count"),
            GFE_Events=("PE level GFE", "sum")  # sum of booleans => count of True
        )
        .reset_index()
    )

    st.write("### 2) Distinct Product Event Summary (PE-Level)")
    st.dataframe(summary_pe)

    csv_data_pe = summary_pe.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download PE-Level Summary",
        data=csv_data_pe,
        file_name="workflow_pe_summary.csv",
        mime="text/csv"
    )

    # -----------------------------------------------------
    # (Optional) You can still view row-level data or row-level summaries
    # -----------------------------------------------------
    st.write("### 3) (Optional) Row-Level Summary for Reference")
    row_summary = (
        df.groupby(["PE level Workflow", "TeamFile", "Source System – PE"])
        .agg(
            Row_GFE_Count=("IsGFE", "sum"),
            Total_Rows=("IsGFE", "count")
        )
        .reset_index()
    )
    st.dataframe(row_summary)

    csv_data_row = row_summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Row-Level Summary",
        data=csv_data_row,
        file_name="workflow_row_level_summary.csv",
        mime="text/csv"
    )

    # -----------------------------------------------------
    # 8) Show the full DataFrame by file (if desired)
    # -----------------------------------------------------
    with st.expander("4) See Full Classified Data (by File)"):
        for team_name in df["TeamFile"].unique():
            st.write(f"**Team File:** {team_name}")
            subset_df = df[df["TeamFile"] == team_name].copy()
            st.dataframe(subset_df)

            csv_data = subset_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"Download '{team_name}' Full Classified Data",
                data=csv_data,
                file_name=f"{team_name}_classified.csv",
                mime="text/csv"
            )
