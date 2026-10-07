import base64

import pandas as pd
import plotly.express as px
import dash_leaflet as dl

from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output

from animal_shelter import AnimalShelter


# Connect to MongoDB
# Credentials are read from environment variables inside AnimalShelter.

shelter = AnimalShelter()

# Initial load. "All" produces an empty $match, so every record is returned,
# already projected to the dashboard fields with age_in_weeks / age_in_years
# calculated by MongoDB (no Pandas age preparation needed anymore).
df = pd.DataFrame.from_records(shelter.read_rescue_filter("All"))

print("DataFrame columns:")
print(df.columns.tolist())

print("\nNumber of records:")
print(len(df))


# Load logo

image_filename = "Grazioso Salvare Logo.png"

with open(image_filename, "rb") as image_file:
    encoded_image = base64.b64encode(
        image_file.read()
    ).decode()


# Build Dashboard

app = Dash(__name__)

app.layout = html.Div([

    html.A(
        html.Center(
            html.Img(
                src=f"data:image/png;base64,{encoded_image}",
                height=250,
                width=251
            )
        ),
        href="https://www.snhu.edu",
        target="_blank"
    ),

    html.Center(
        html.H1(
            "Cooper David SNHU CS-340 Dashboard"
        )
    ),

    html.Hr(),

    # Radio buttons match the keys in RESCUE_FILTERS ("All" means no filter)
    dcc.RadioItems(
        id="filter-type",
        options=[
            {
                "label": "All",
                "value": "All"
            },
            {
                "label": "Water Rescue",
                "value": "Water"
            },
            {
                "label": "Mountain or Wilderness Rescue",
                "value": "Mountain"
            },
            {
                "label": "Disaster Rescue or Individual Tracking",
                "value": "Disaster"
            }
        ],
        value="All"
    ),

    html.Hr(),

    dash_table.DataTable(
        id="datatable-id",

        columns=[
            {
                "name": column,
                "id": column,
                "deletable": False,
                "selectable": True
            }
            for column in df.columns
        ],

        data=df.to_dict("records"),

        editable=True,

        row_selectable="single",

        selected_rows=[],

        filter_action="native",

        sort_action="native",

        page_action="native",

        page_current=0,

        page_size=10
    ),

    html.Br(),

    html.Hr(),

    html.Div(
        style={
            "display": "flex",
            "justify-content": "center"
        },

        children=[

            html.Div(
                id="graph-id",
                style={
                    "width": "50%"
                }
            ),

            html.Div(
                id="map-id",
                style={
                    "width": "50%"
                }
            )
        ]
    )
])


# Filter Data
# Filtering now happens inside MongoDB (aggregation pipeline with $match and
# $project), so only the matching records are sent back to Python.

@app.callback(
    Output("datatable-id", "data"),
    Input("filter-type", "value")
)
def update_dashboard(filter_type):

    return shelter.read_rescue_filter(filter_type)


# Highlight selected columns

@app.callback(
    Output("datatable-id", "style_data_conditional"),
    Input("datatable-id", "selected_columns")
)
def update_styles(selected_columns):

    if not selected_columns:
        return []

    return [
        {
            "if": {
                "column_id": column
            },

            "background_color": "#D2F3FF"
        }

        for column in selected_columns
    ]


# Pie Chart

@app.callback(
    Output("graph-id", "children"),
    Input("datatable-id", "derived_virtual_data")
)
def update_graphs(viewData):

    # Empty filter results (for example, no Water Rescue matches)
    if not viewData:
        return html.Div(
            "No data to display for the selected filter."
        )

    dff = pd.DataFrame.from_dict(viewData)

    return dcc.Graph(
        figure=px.pie(
            dff,
            names="breed",
            title="Animal Breeds"
        )
    )


# Map
# derived_virtual_selected_rows is an index into the table as currently shown
# (after filtering / sorting), so it needs to be used with derived_virtual_data
# rather than with the full dataframe.

@app.callback(
    Output("map-id", "children"),
    [
        Input("datatable-id", "derived_virtual_selected_rows"),
        Input("datatable-id", "derived_virtual_data")
    ]
)
def update_map(virtualRows, viewData):

    # Default location
    if not virtualRows or not viewData:

        markerArray = (
            30.75,
            -97.48
        )

        toolTip = "Austin Animal Center"

        popUpHeading = "Austin Animal Center"

        popUpParagraph = "Shelter Home Location"

    else:

        # Look up the selected row in the data currently displayed in the table
        row = pd.DataFrame.from_dict(viewData).iloc[virtualRows[0]]

        markerArray = (
            float(row["location_lat"]),
            float(row["location_long"])
        )

        toolTip = str(row["breed"])

        popUpHeading = "Animal Name"

        popUpParagraph = str(row["name"])

    return dl.Map(

        style={
            "width": "700px",
            "height": "450px"
        },

        center=markerArray,

        zoom=10,

        children=[

            dl.TileLayer(
                id="base-layer-id"
            ),

            dl.Marker(
                position=markerArray,

                children=[

                    dl.Tooltip(toolTip),

                    dl.Popup([

                        html.H1(popUpHeading),

                        html.P(popUpParagraph)

                    ])
                ]
            )
        ]
    )


# Run application

if __name__ == "__main__":
    app.run(debug=True)