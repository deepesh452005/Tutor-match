import math


def haversine_km(lat1, lon1, lat2, lon2):
    """Straight-line distance between two lat/long points, in km."""
    R = 6371  # Earth's radius in km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def find_matching_tutors(search, tutors):
    """
    search = {
        "subject": "Mathematics",
        "class": 8,
        "from_hour": 17,      # 5 PM
        "to_hour": 18,        # 6 PM
        "radius_km": 5,
        "lat": 17.44,
        "lon": 78.38,
    }
    tutors = list of dicts with: name, subjects (list), min_class, max_class,
             available_from, available_to, lat, lon
    Returns the matching tutors, nearest first.
    """
    matches = []

    for tutor in tutors:
        # Gate 1: subject
        subject = search.get("subject")
        subjects = [s.strip().lower() for s in tutor["subjects"]]
        if subject and subject.strip().lower() not in subjects:
            continue

        # Gate 2: class
        class_level = search.get("class")
        if class_level is not None and not (tutor["min_class"] <= class_level <= tutor["max_class"]):
            continue

        # Gate 3: timing (student's slot must fit fully inside tutor's window)
        from_hour = search.get("from_hour")
        to_hour = search.get("to_hour")
        if from_hour is not None and to_hour is not None and not (
            tutor["available_from"] <= from_hour and to_hour <= tutor["available_to"]
        ):
            continue

        # Gate 4: distance
        distance = haversine_km(search["lat"], search["lon"], tutor["lat"], tutor["lon"])
        radius_km = search.get("radius_km")
        if radius_km is not None and distance > radius_km:
            continue

        # Passed all 4 gates
        result = dict(tutor)
        result["distance_km"] = round(distance, 1)
        matches.append(result)

    matches.sort(key=lambda t: t["distance_km"])
    return matches