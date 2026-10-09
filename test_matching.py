from matching import find_matching_tutors

# Student's home. Tutors below are placed at exact distances north of it.
BASE_LAT, BASE_LON = 17.4400, 78.3800


def km_north(km):
    """Latitude of a point that is `km` kilometres north of the base."""
    return BASE_LAT + km / 111.195


tutors = [
    {   # Should MATCH
        "name": "Tutor 1", "subjects": ["Mathematics"],
        "min_class": 6, "max_class": 10,
        "available_from": 16, "available_to": 19,
        "lat": km_north(2.3), "lon": BASE_LON,
    },
    {   # Fails timing (free 7-9 PM, student wants 5-6 PM)
        "name": "Tutor 2", "subjects": ["Mathematics"],
        "min_class": 8, "max_class": 10,
        "available_from": 19, "available_to": 21,
        "lat": km_north(1.5), "lon": BASE_LON,
    },
    {   # Fails distance (7.2 km away)
        "name": "Tutor 3", "subjects": ["Mathematics"],
        "min_class": 6, "max_class": 10,
        "available_from": 17, "available_to": 19,
        "lat": km_north(7.2), "lon": BASE_LON,
    },
    {   # Fails class (teaches only 1-5)
        "name": "Tutor 4", "subjects": ["Mathematics"],
        "min_class": 1, "max_class": 5,
        "available_from": 16, "available_to": 20,
        "lat": km_north(1.0), "lon": BASE_LON,
    },
    {   # Fails subject (teaches Physics, not Maths)
        "name": "Tutor 5", "subjects": ["Physics"],
        "min_class": 6, "max_class": 10,
        "available_from": 16, "available_to": 20,
        "lat": km_north(1.0), "lon": BASE_LON,
    },
]

search = {
    "subject": "Mathematics",
    "class": 8,
    "from_hour": 17,   # 5 PM
    "to_hour": 18,     # 6 PM
    "radius_km": 5,
    "lat": BASE_LAT,
    "lon": BASE_LON,
}

results = find_matching_tutors(search, tutors)

print(f"{len(tutors)} tutors checked -> {len(results)} matching\n")
for t in results:
    print(f"  ✅ {t['name']} - {t['distance_km']} km away")

# Automatic check: only Tutor 1 should survive
assert [t["name"] for t in results] == ["Tutor 1"], "Something is wrong in the matching!"
print("\nAll good, the sieve works!")

unfiltered_results = find_matching_tutors(
    {"subject": None, "class": None, "from_hour": None, "to_hour": None,
     "radius_km": None, "lat": BASE_LAT, "lon": BASE_LON},
    tutors,
)
assert {t["name"] for t in unfiltered_results} == {t["name"] for t in tutors}
print("Unfiltered search includes every tutor profile.")