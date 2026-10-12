"""Port of kjellrg/zwift-bikes forces.ts and rider sizing; see data licenses.

A community approximation, not Zwift's official engine. Baseline generic road
bike: 8 kg, equipment CdA 0.32, road wheels, solo/no drafting or powerups.
"""

import json
import math
from pathlib import Path

MODEL = json.loads((Path(__file__).parent / "data/model.json").read_text())
G, RHO, EFFICIENCY = MODEL["gravity"], MODEL["air_density"], MODEL["efficiency"]


def rider_cda(height_cm, weight_kg):
    return (
        0.0293 * (max(1, height_cm) / 100) ** 0.725 * max(30, weight_kg) ** 0.425
        + 0.0604
    )


def forces(speed, grade, power, weight, cda, surface="tarmac"):
    mass = weight + MODEL["bike_mass"]
    angle = math.atan(grade)
    speed = max(0, speed)
    driving = power * EFFICIENCY / max(speed, 0.1) if power > 0 else 0
    gravity = mass * G * math.sin(angle)
    rolling = MODEL["crr"][surface] * mass * G * math.cos(angle)
    aero = 0.5 * RHO * cda * speed**2
    net = driving - gravity - rolling - aero
    return driving, gravity, rolling, aero, net, net / mass


def power_for_speed(speed, mass, grade, crr, cda):
    angle = math.atan(grade)
    return (
        (crr * mass * G * math.cos(angle) + mass * G * math.sin(angle)) * speed
        + 0.5 * RHO * cda * speed**3
    ) / EFFICIENCY


def speed_for_power(power, mass, grade, crr, cda):
    lo, hi = 0.1, 40
    for _ in range(40):
        mid = (lo + hi) / 2
        if power_for_speed(mid, mass, grade, crr, cda) < power:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def travel(segments, power, weight, height, *, step=1):
    """Integrate each slope with persistent speed and a stable startup step.

    Heun integration with adaptive acceleration step; split at segment edges.
    Speed is never reset at a hill or lap boundary.
    """
    cda, speed, elapsed = rider_cda(height, weight), 0.1, 0
    for distance, rise, surface in segments:
        grade, covered = rise / distance, 0
        while covered < distance:
            accel = forces(speed, grade, power, weight, cda, surface)[-1]
            dt = min(step, 0.1 * max(speed, 0.1) / max(abs(accel), 0.001))
            predicted = max(0.01, speed + accel * dt)
            a2 = forces(predicted, grade, power, weight, cda, surface)[-1]
            next_speed = max(0.01, speed + (accel + a2) * dt / 2)
            moved = (speed + next_speed) * dt / 2
            fraction = min(1, (distance - covered) / moved)
            elapsed += dt * fraction
            covered += moved * fraction
            speed += (next_speed - speed) * fraction
            if elapsed > 172800:
                raise ValueError("Course exceeds model duration limit")
    return elapsed


def coarse(distance, ascent, power, weight, height):
    flat = distance / speed_for_power(
        power,
        weight + MODEL["bike_mass"],
        0,
        MODEL["crr"]["tarmac"],
        rider_cda(height, weight),
    )
    return flat + (weight + MODEL["bike_mass"]) * G * (ascent or 0) / (
        power * EFFICIENCY
    )
