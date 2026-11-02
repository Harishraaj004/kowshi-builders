"""
app/tools.py
=============
Deterministic Python "tools" the AI can call - and the one hard rule this
file exists to enforce: **never let the LLM do arithmetic that Python can
do reliably.**

WHY THIS MATTERS FOR A CONSTRUCTION ESTIMATOR
------------------------------------------------
LLMs are genuinely unreliable at exact arithmetic - they generate answers
token by token based on patterns in training data, not by actually running
a calculation. So instead of asking Claude to compute a price, we give it
a Python FUNCTION that computes it exactly, and let Claude decide WHEN to
call it and how to explain the result in plain language. Claude never
runs the code itself - it only ever asks for it; WE run it (see the
agentic loop in app/llm.py) and hand the result back.

WHAT CHANGED IN THIS VERSION
--------------------------------
Earlier, pricing was based on a "basic/standard/premium" quality tier.
Now pricing is based on LOCATION instead - a real, per-square-foot rate
that varies by construction site - plus two new inputs that affect the
total: how many FLOORS, and whether CAR PARKING is included. This is a
more realistic model of how an actual construction quote gets built up:
floors multiply the built-up area, car parking adds its own (cheaper,
because it's simpler construction) area on top, and the per-sq-ft rate
itself depends on where you're building.

IMPORTANT CAVEAT ON THE NUMBERS BELOW
----------------------------------------
The rates in RATE_PER_SQFT_BY_LOCATION, and the car-parking/timeline
assumptions, are illustrative placeholder values for learning purposes -
NOT audited, real-world construction pricing. Before this powers a real
quotation, these need to come from an actual, maintained rate card.
Stage 5 (RAG) is where we'll eventually pull domain data like this from
real documents instead of hardcoded constants - one problem at a time.
"""


# --- Domain data (placeholder!) -----------------------------------------
# A real system would load this from a database or document (Stage 5),
# not hardcode it in source. For now, a plain dict keeps the CONCEPT
# (Claude calls a tool, Python does the math) separate from the DATA
# problem (getting real, current rates) - one thing to learn at a time.
#
# Keys are lowercase so lookups are case-insensitive (see
# estimate_construction_quote() below) - Claude might send "Chennai" or
# "chennai" depending on how the user typed it.
RATE_PER_SQFT_BY_LOCATION = {
    "chennai": 3000,
    "chengalpattu": 2500,
    "mahabalipuram": 2700,
    "kancheepuram": 2700,
}

# A standard covered car-parking area, in square feet - roughly enough
# for one car plus walking room. This gets ADDED to the built-up area
# when the customer wants parking, before the total cost is calculated.
CAR_PARKING_AREA_SQFT = 100

# Parking sheds are simpler construction than living space (no interior
# finishing, plumbing, electrical fixtures, etc.), so we charge that
# extra area at half the location's normal per-sq-ft rate - a
# simplification, but a reasonable, explainable one.
CAR_PARKING_RATE_MULTIPLIER = 0.5

# How many square feet of built-up area a construction crew can
# typically complete in one month - used only for the timeline estimate.
# Unlike cost, we're treating pace as the SAME everywhere for now (real
# pace varies by location too, but we don't have that data yet).
BASE_PACE_SQFT_PER_MONTH = 400

# Building UP takes longer than building the same total area as a single
# spread-out floor - each additional floor adds sequential work (its own
# structural/foundation stage) on top of the raw area calculation. This
# is a rough, illustrative rule of thumb, not an engineering formula.
EXTRA_MONTHS_PER_ADDITIONAL_FLOOR = 1

# Adding a parking shed is comparatively quick, but not instant.
EXTRA_MONTHS_FOR_CAR_PARKING = 0.5


def estimate_construction_quote(
    area_sqft_per_floor: float,
    floors: int,
    with_car_parking: bool,
    location: str,
) -> dict:
    """
    Calculates a full construction quote: cost breakdown AND an
    estimated timeline, all in one call - since by the time we have all
    four inputs below, giving a complete answer is more useful than
    forcing a second round-trip for the timeline.

    This is a plain Python function - no AI involved in the arithmetic
    itself. Claude decides WHEN to call it (once it has gathered all
    four pieces of information from the user) and HOW to phrase the
    result; this function's only job is to get the numbers right, every
    time, the same way.

    Parameters
    ----------
    area_sqft_per_floor : float
        The built-up area of ONE floor, in square feet. Multiplied by
        `floors` below to get the total area actually being built.
    floors : int
        How many floors, e.g. 1 for a single-storey house, 2 for a
        ground + first floor ("G+1") house.
    with_car_parking : bool
        Whether to include a covered car-parking area in the quote.
    location : str
        One of the keys in RATE_PER_SQFT_BY_LOCATION (case-insensitive) -
        currently "chennai", "chengalpattu", "mahabalipuram", or
        "kancheepuram".

    Returns
    -------
    dict
        A full breakdown Claude can read and explain, e.g.:
        {"location": "Chennai", "rate_per_sqft": 3000,
         "area_sqft_per_floor": 1500, "floors": 1,
         "total_built_up_area": 1500, "with_car_parking": True,
         "base_cost": 4500000, "car_parking_cost": 150000,
         "total_cost": 4650000, "material_cost": 2790000,
         "labour_cost": 1860000, "estimated_months": 4.5,
         "currency": "INR"}

    Raises
    ------
    ValueError
        If `location` isn't one of the known keys, or if `area_sqft_per_
        floor`/`floors` aren't positive numbers. This lets the CALLER
        (execute_tool below) turn the failure into a `tool_result` with
        `is_error: True`, so Claude can react sensibly (ask a clarifying
        question) instead of the whole request crashing.
    """
    location_key = location.strip().lower()

    if location_key not in RATE_PER_SQFT_BY_LOCATION:
        valid_options = ", ".join(
            key.title() for key in RATE_PER_SQFT_BY_LOCATION
        )
        raise ValueError(
            f"Unknown location '{location}'. We currently only have "
            f"rates for: {valid_options}."
        )

    if area_sqft_per_floor <= 0:
        raise ValueError("area_sqft_per_floor must be a positive number.")

    if floors < 1:
        raise ValueError("floors must be at least 1.")

    rate_per_sqft = RATE_PER_SQFT_BY_LOCATION[location_key]

    # The core calculation: how much TOTAL area are we actually
    # building? A "G+1" (ground + 1st floor) house with 1200 sq ft per
    # floor means 2400 sq ft of total construction, not 1200 - each
    # floor needs its own full slab, walls, wiring, etc.
    total_built_up_area = area_sqft_per_floor * floors
    base_cost = total_built_up_area * rate_per_sqft

    car_parking_cost = 0.0
    if with_car_parking:
        car_parking_cost = (
            CAR_PARKING_AREA_SQFT * rate_per_sqft * CAR_PARKING_RATE_MULTIPLIER
        )

    total_cost = base_cost + car_parking_cost

    # A commonly-cited rough split for a ballpark estimate: about 60% of
    # a construction budget goes to materials, 40% to labour. Real
    # numbers vary a lot by project - this is illustrative, not
    # authoritative.
    material_cost = total_cost * 0.6
    labour_cost = total_cost * 0.4

    # Timeline: base pace, PLUS extra time for each additional floor
    # (sequential vertical construction), PLUS a little extra if there's
    # a parking shed to build too.
    base_months = total_built_up_area / BASE_PACE_SQFT_PER_MONTH
    floor_overhead_months = (floors - 1) * EXTRA_MONTHS_PER_ADDITIONAL_FLOOR
    parking_overhead_months = EXTRA_MONTHS_FOR_CAR_PARKING if with_car_parking else 0
    estimated_months = max(
        1, round(base_months + floor_overhead_months + parking_overhead_months, 1)
    )

    return {
        "location": location_key.title(),
        "rate_per_sqft": rate_per_sqft,
        "area_sqft_per_floor": area_sqft_per_floor,
        "floors": floors,
        "total_built_up_area": total_built_up_area,
        "with_car_parking": with_car_parking,
        "base_cost": round(base_cost, 2),
        "car_parking_cost": round(car_parking_cost, 2),
        "total_cost": round(total_cost, 2),
        "material_cost": round(material_cost, 2),
        "labour_cost": round(labour_cost, 2),
        "estimated_months": estimated_months,
        "currency": "INR",
    }


# --- Tool definitions (what Claude actually sees) -------------------------
# A JSON Schema description of the function above - a name, a description
# (Claude uses THIS TEXT to decide WHEN to call the tool), and
# input_schema (the exact shape of arguments Claude must provide). Claude
# never sees the Python code above - only this description.
TOOLS = [
    {
        "name": "estimate_construction_quote",
        "description": (
            "Calculates a full construction quote (cost breakdown AND "
            "estimated timeline) for a house, given its per-floor "
            "built-up area, number of floors, whether car parking is "
            "wanted, and the construction location. Call this ONLY "
            "after you have gathered ALL FOUR pieces of information "
            "from the user, one question at a time - never call this "
            "with a guessed or default value for any field, and never "
            "calculate or estimate a cost/timeline yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "area_sqft_per_floor": {
                    "type": "number",
                    "description": "The built-up area of ONE floor, in square feet.",
                },
                "floors": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Number of floors, e.g. 1 for a single-storey house, 2 for ground + first floor.",
                },
                "with_car_parking": {
                    "type": "boolean",
                    "description": "Whether the customer wants a covered car-parking area included.",
                },
                "location": {
                    "type": "string",
                    "enum": ["chennai", "chengalpattu", "mahabalipuram", "kancheepuram"],
                    "description": "The construction site's location. Must be one of the four supported locations - present these as options to the user.",
                },
            },
            "required": ["area_sqft_per_floor", "floors", "with_car_parking", "location"],
        },
    },
]

# Maps a tool NAME (a string, as it arrives in a tool_use block from
# Claude) to the actual Python function that implements it.
TOOL_FUNCTIONS = {
    "estimate_construction_quote": estimate_construction_quote,
}


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Runs the tool Claude asked for, and always returns a JSON-serializable
    result - success or a structured error - and never raises. Callers
    (app/llm.py's agentic loop) don't need a try/except around this; they
    just check whether the returned dict has an "error" key.

    Parameters
    ----------
    tool_name : str
        Which tool to run - matches a key in TOOL_FUNCTIONS, and a "name"
        in TOOLS above.
    tool_input : dict
        The arguments Claude provided, already parsed from JSON by the
        Anthropic SDK.

    Returns
    -------
    dict
        Either the tool function's normal return value, or
        {"error": "..."} if something went wrong.
    """
    function = TOOL_FUNCTIONS.get(tool_name)

    if function is None:
        # Shouldn't normally happen - Claude only ever requests tool names
        # we told it about in TOOLS - but guarding against it means a
        # typo or future mismatch between TOOLS and TOOL_FUNCTIONS fails
        # loudly and recoverably instead of crashing the whole request.
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        # The ** unpacks the tool_input dict into keyword arguments.
        return function(**tool_input)
    except (ValueError, TypeError) as error:
        # ValueError: our own validation inside the function (unknown
        # location, non-positive area/floors). TypeError: Claude
        # provided arguments that don't match the function's signature
        # at all - rare given input_schema validation, but worth
        # catching explicitly rather than letting the whole request
        # crash.
        return {"error": str(error)}
