import os
from urllib.parse import quote_plus

from pymongo import MongoClient, ASCENDING
from bson.objectid import ObjectId


# ---------------------------------------------------------------------------
# Rescue-type search rules
# The dashboard used to hold these lists and filter in Pandas. They now live in
# the database layer so MongoDB does the filtering.
# max_weeks = None means "no upper age limit" (same as the original Disaster filter).
# ---------------------------------------------------------------------------
RESCUE_FILTERS = {
    "Water": {
        "breeds": [
            "Labrador Retriever Mix",
            "Chesapeake Bay Retriever",
            "Newfoundland",
        ],
        "sex": "Female",
        "min_weeks": 26,
        "max_weeks": 156,
    },
    "Mountain": {
        "breeds": [
            "German Shepherd",
            "Alaskan Malamute",
            "Old English Sheepdog",
            "Siberian Husky",
            "Rottweiler",
        ],
        "sex": "Intact Male",
        "min_weeks": 26,
        "max_weeks": 156,
    },
    "Disaster": {
        "breeds": [
            "Doberman Pinscher",
            "German Shepherd",
            "Golden Retriever",
            "Bloodhound",
            "Rottweiler",
        ],
        "sex": "Intact Male",
        "min_weeks": 20,
        "max_weeks": None,
    },
}

# Only the fields the dashboard needs are returned by the $project stage.
DASHBOARD_FIELDS = [
    "animal_id",
    "animal_type",
    "name",
    "breed",
    "color",
    "date_of_birth",
    "sex_upon_outcome",
    "age_upon_outcome",
    "age_upon_outcome_in_weeks",
    "outcome_type",
    "outcome_subtype",
    "location_lat",
    "location_long",
]

# Used to convert age in weeks to age in years
WEEKS_PER_YEAR = 52.1429


class AnimalShelter():
    """ CRUD operations for Animal collection in MongoDB """

    def __init__(self):
        # Credentials come from environment variables, never from source code.
        # .strip() guards against stray spaces copied into the variable.
        USER = (os.environ.get("MONGO_USER") or "").strip()
        PASS = (os.environ.get("MONGO_PASSWORD") or "").strip()
        HOST = (os.environ.get("MONGO_HOST") or "").strip()
        PORT = (os.environ.get("MONGO_PORT") or "").strip()  # optional, isn't used with mongodbAtlas

        DB = 'NEWAAC'
        COL = 'animals'

        # Report which variables are missing (names only, never values)
        missing = [
            name for name, value in (
                ("MONGO_USER", USER),
                ("MONGO_PASSWORD", PASS),
                ("MONGO_HOST", HOST),
            ) if not value
        ]
        if missing:
            raise ValueError(
                "MongoDB environment variables are not configured: "
                + ", ".join(missing)
            )

        # Hide special characters
        user = quote_plus(USER)
        password = quote_plus(PASS)

        if PORT:
            # Standard connection (local or self-hosted MongoDB)
            uri = f"mongodb://{user}:{password}@{HOST}:{PORT}/"
        else:
            # Atlas style connection (host only, no port allowed)
            uri = f"mongodb+srv://{user}:{password}@{HOST}/?appName=Cluster0"

        # Initialize Connection (fail fast after 5 seconds if the server is unreachable)
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.database = self.client[DB]
        self.collection = self.database[COL]

        # Make sure the indexes used by the dashboard queries exist
        self._ensure_indexes()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def _ensure_indexes(self):
        """
        Create indexes for the fields the dashboard filters on.
        """
        try:
            # Compound index is ordered in this way: exact match -> $in match -> range.
            # That order matches the rescue queries, so MongoDB can narrow
            # the search at each step instead of scanning every document.
            # It also serves queries on sex_upon_outcome alone,
            # so a separate single field sex index wouldn't be needed.
            self.collection.create_index(
                [
                    ("sex_upon_outcome", ASCENDING),
                    ("breed", ASCENDING),
                    ("age_upon_outcome_in_weeks", ASCENDING),
                ],
                name="rescue_compound_idx",
            )

            # Single field indexes for queries that don't use the compound prefix
            self.collection.create_index(
                [("breed", ASCENDING)], name="breed_idx"
            )
            self.collection.create_index(
                [("age_upon_outcome_in_weeks", ASCENDING)], name="age_weeks_idx"
            )
        except Exception as e:
            # For example, the database user might not have createIndex privileges
            print(f"Could not confirm indexes: {e}")

    # ------------------------------------------------------------------
    # Aggregation-based search
    # ------------------------------------------------------------------
    @staticmethod
    def _build_match(rescue_type):
        """Translate a rescue type into a MongoDB filter ({} matches everything)."""
        rule = RESCUE_FILTERS.get(rescue_type)

        # "All", None, or an unknown type -> empty filter
        if rule is None:
            return {}

        # Age range: always a lower bound, upper bound only if defined
        age = {"$gte": rule["min_weeks"]}
        if rule["max_weeks"] is not None:
            age["$lte"] = rule["max_weeks"]

        return {
            "sex_upon_outcome": rule["sex"],
            "breed": {"$in": rule["breeds"]},
            "age_upon_outcome_in_weeks": age,
        }

    def build_pipeline(self, rescue_type=None):
        """
        Build the aggregation pipeline:
          $match   - filter documents
          $project - keep only needed fields and calculate age values
        """
        # Safely convert the stored age to a number (null if conversion fails)
        weeks = {
            "$convert": {
                "input": "$age_upon_outcome_in_weeks",
                "to": "double",
                "onError": None,
                "onNull": None,
            }
        }

        # Start by excluding _id, then include only the dashboard fields
        project = {"_id": 0}
        for field in DASHBOARD_FIELDS:
            project[field] = 1

        # Calculated fields, ran by MongoDB instead of Pandas
        project["age_in_weeks"] = weeks
        project["age_in_years"] = {
            "$round": [{"$divide": [weeks, WEEKS_PER_YEAR]}, 1]
        }

        return [
            {"$match": self._build_match(rescue_type)},
            {"$project": project},
        ]

    def read_rescue_filter(self, rescue_type=None):
        """
        Server side filtering and age calculation for the dashboard.
        rescue_type: "Water", "Mountain", "Disaster", or None/"All" for everything.
        Returns a list of dictionaries the dashboard can use directly.
        """
        try:
            return list(self.collection.aggregate(self.build_pipeline(rescue_type)))
        except Exception as e:
            print(f"An error has occurred: {e}")
            return []  # Empty list keeps the dashboard from crashing

    # ------------------------------------------------------------------
    # CRUD methods
    # ------------------------------------------------------------------

    # Creating C Method
    def create(self, data):
        if data is not None:
            try:
                insert_success = self.collection.insert_one(data)
                return insert_success.inserted_id is not None
            except Exception as e:
                print(f"An error has occurred: {e}")
        else:
            print("Data parameter is empty, cannot save")

    # Creating R method
    def read(self, searchData):
        if searchData is not None:
            try:
                data = list(self.collection.find(searchData, {"_id": False}))
                return data
            except Exception as e:
                print(f"An error has occurred: {e}")
                return []  # Return an empty list in case of error
        else:
            data = list(self.collection.find({}, {"_id": False}))
            return data

    # Creating U method
    def update(self, searchData, updateData):
        if searchData is not None:
            try:
                result = self.collection.update_many(searchData, {"$set": updateData})
                return result.raw_result
            except Exception as e:
                print(f"An error has occurred: {e}")
                return {}

    # Creating D method
    def delete(self, deleteData):
        if deleteData is not None:
            try:
                result = self.collection.delete_many(deleteData)
                return result.raw_result
            except Exception as e:
                print(f"An error has occurred: {e}")
                return {}