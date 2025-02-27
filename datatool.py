import streamlit as st
import pandas as pd

st.title("Excel File Merger & Filter Tool")

# Upload multiple files
uploaded_files = st.file_uploader("Upload Excel Files", type=["xls", "xlsx"], accept_multiple_files=True)

dataframes = {}

if uploaded_files:
    for file in uploaded_files:
        xls = pd.ExcelFile(file)
        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name)
            dataframes[sheet_name] = df
    
    # Display the dataset preview
    st.write("### Uploaded Sheets")
    selected_sheet = st.selectbox("Select a sheet to view", list(dataframes.keys()))
    combined_df = dataframes[selected_sheet]
    st.dataframe(combined_df)
    
    # Get columns for filtering and sorting
    columns = combined_df.columns.tolist()
    
    # Sorting options
    sort_column = st.selectbox("Select column to sort by", columns)
    sort_order = st.radio("Sort order", ["Ascending", "Descending"], index=0)
    
    # Filtering options
    filter_column = st.selectbox("Select column to filter by", columns)
    filter_value = st.text_input("Enter filter value")
    
    # Apply sorting and filtering
    sorted_df = combined_df.sort_values(by=sort_column, ascending=(sort_order == "Ascending"))
    if filter_value:
        filtered_df = sorted_df[sorted_df[filter_column].astype(str).str.contains(filter_value, case=False, na=False)]
    else:
        filtered_df = sorted_df
    
    # Display filtered results
    st.write("### Filtered Data")
    st.dataframe(filtered_df)
    
    # Count and sum based on filtering
    st.write("### Summary Statistics")
    st.write(f"Total Rows After Filtering: {len(filtered_df)}")
    for col in filtered_df.select_dtypes(include=['number']).columns:
        st.write(f"Sum of {col}: {filtered_df[col].sum()}")
    
    # Download option
    csv = filtered_df.to_csv(index=False).encode('utf-8')
    st.download_button(label="Download CSV", data=csv, file_name="filtered_data.csv", mime='text/csv')
