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

    # -----------------------------------------------------------------
    # STEP A: Flag GFE rows (row-level)
    # -----------------------------------------------------------------
    gfe_keywords = ["Follow-up for Prod/Info", "Follow Up for Information"]
    df["IsGFE"] = df["Communication"].apply(
        lambda val: any(k in str(val) for k in gfe_keywords)
    )

    # -----------------------------------------------------------------
    # STEP B: PLI-Level KnowledgeClass
    #         1) Group by PE - PLI # to see distinct RFR codes
    # -----------------------------------------------------------------
    pli_rfr_count = (
        df.groupby("PE - PLI #")["RFR Codes"]
        .nunique()
        .rename("pli_num_distinct_rfr")
    )

    # Frequency of each RFR code across the entire dataset
    rfr_freq = df["RFR Codes"].value_counts().to_dict()

    # Merge pli_rfr_count back into df
    df = df.merge(pli_rfr_count, on="PE - PLI #", how="left")

    def classify_pli_level(row):
        """Classify each row based on its PLI # group."""
        # If that PLI # has > 1 distinct RFR => Not Well Understood
        if row["pli_num_distinct_rfr"] > 1:
            return "Not Well Understood"
        else:
            # If only 1 distinct RFR code, check how common that code is overall
            freq = rfr_freq.get(row["RFR Codes"], 0)
            return "Well Understood" if freq >= 50 else "Not Well Understood"

    df["PLI level KnowledgeClass"] = df.apply(classify_pli_level, axis=1)

    # -----------------------------------------------------------------
    # STEP C: PE-Level KnowledgeClass
    #         If ANY PLI in the same Product Event ID is Not Well Understood,
    #         then the entire Product Event ID is Not Well Understood
    # -----------------------------------------------------------------
    df["PE level KnowledgeClass"] = df.groupby("Product Event ID")["PLI level KnowledgeClass"].transform(
        lambda group: "Not Well Understood"
                      if "Not Well Understood" in group.values
                      else "Well Understood"
    )

    # -----------------------------------------------------------------
    # STEP D: Region & FDA checks
    # -----------------------------------------------------------------
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

    # -----------------------------------------------------------------
    # STEP E: PE-Level Workflow
    #         => use "PE level KnowledgeClass" for entire product event
    # -----------------------------------------------------------------
    def classify_pe_workflow(row):
        country = str(row.get("Country – PE", "")).strip().title()
        knowledge = row.get("PE level KnowledgeClass", "")
        rep_text = str(row.get("Reportability", "")).upper()

        us_terr = is_us_territory(country)
        eu = is_eu(country)
        canada = is_canada(country)
        japan = is_japan(country)
        gchina = is_greater_china(country)
        fda_rep = is_fda_reportable(rep_text)

        # Workflow 1
        if us_terr and (not fda_rep) and (knowledge == "Well Understood"):
            return 1

        # Workflow 2
        if knowledge == "Well Understood":
            if (us_terr and fda_rep) or eu or canada:
                return 2

        # Workflow 3
        if (us_terr or eu or canada) and (knowledge == "Not Well Understood"):
            return 3

        # Workflow 4
        is_ous_other = (
            not us_terr
            and not eu
            and not canada
            and not japan
            and not gchina
        )
        if is_ous_other:
            return 4

        # Workflow 5
        if japan or gchina:
            return 5

        # Otherwise
        return 0

    df["PE level Workflow"] = df.apply(classify_pe_workflow, axis=1)

    # -----------------------------------------------------------------
    # STEP F: PE-level GFE
    #         => If ANY row in the same Product Event ID is GFE => entire event is GFE
    # -----------------------------------------------------------------
    df["PE level GFE"] = df.groupby("Product Event ID")["IsGFE"].transform(any)

    # -----------------------------------------------------------------
    # STEP G: Summaries at the Product Event ID level
    #         => 1 count per unique Product Event
    # -----------------------------------------------------------------
    # We drop duplicates so each Product Event ID is listed once
    df_pe = df.drop_duplicates(subset=["Product Event ID"]).copy()

    summary_pe = (
        df_pe.groupby(["PE level Workflow", "TeamFile", "Source System – PE"])
        .agg(
            # Distinct_Product_Events=("Product Event ID", "count"),
            GFE_Events=("PE level GFE", "sum")  # sum of booleans => # of GFE
        )
        .reset_index()
    )

    st.write("### 2) Product Event Summary (PE-Level)")
    st.write("_(Distinct Product Events are counted once; only GFE_Events shown.)_")
    st.dataframe(summary_pe)

    # -----------------------------------------------------------------
    # STEP H: PIVOT => Source systems across columns
    #         We'll pivot on "Source System – PE" as columns,
    #         use "PE level Workflow" (and optionally TeamFile) as rows,
    #         and fill with GFE_Events. 
    # -----------------------------------------------------------------
    # Example pivot with both "PE level Workflow" AND "TeamFile" as the row index:
    # pivot_df = summary_pe.pivot_table(
    #     index=["PE level Workflow", "TeamFile"],
    #     columns="Source System – PE",
    #     values="GFE_Events",
    #     aggfunc="sum",        # sum because multiple rows could exist
    #     fill_value=0
    # )
    #
    # If you only want "PE level Workflow" as the row index, do this:

    pivot_df = summary_pe.pivot_table(
        index="PE level Workflow",
        columns="Source System – PE",
        values="GFE_Events",
        aggfunc="sum",
        fill_value=0
    )

    st.write("### 3) Pivot: Source System across columns (GFE Events)")
    st.dataframe(pivot_df)

    # (Optional) Provide a CSV download of pivot
    csv_pivot = pivot_df.reset_index().to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Pivot (GFE Events)",
        data=csv_pivot,
        file_name="pivot_gfe_events.csv",
        mime="text/csv"
    )

    # -----------------------------------------------------------------
    # (OPTIONAL) Row-level details or further expansions
    # -----------------------------------------------------------------
    with st.expander("4) (Optional) See Full Row-Level Data"):
        st.dataframe(df)
        csv_data_row = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Full Row-Level Data",
            data=csv_data_row,
            file_name="row_level_data.csv",
            mime="text/csv"
        )
