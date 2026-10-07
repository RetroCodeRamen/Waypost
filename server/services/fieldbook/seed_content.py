"""Default Fieldbook pages — survival, camping, and wayfinding reference.

Seeded on first run (and any missing slug on later boots). Author is always
``station`` so edits show up in revision history when camp operators refine them.
"""

from __future__ import annotations

# (slug, title, body)
SEED_PAGES: list[tuple[str, str, str]] = [
    (
        "survival-guide",
        "Survival & camping guide",
        """Welcome to the Fieldbook — the camp's shared reference wiki. These pages cover first aid, shelter, plants, animals, navigation, and paddling. Everyone signed in can read and edit.

# What's here
- **First aid** — bleeding, shock, hypothermia, bites
- **Shelter** — tarps, debris shelters, cold weather
- **Plants** — edible basics and poisonous look-alikes
- **Animal sign** — tracks and what they mean
- **Wayfinding** — map, compass, sun, and stars
- **Kayaking** — on-water safety and simple navigation
- **Water** — finding and making water safe
- **Fire** — starting and maintaining fire in wet conditions

Use Finder or search in the Fieldbook app to jump to a topic. Scouts can pull sections over the radio.""",
    ),
    (
        "first-aid",
        "First aid — essentials",
        """# Before you start
Move to safety. Call for help on Beacon if life-threatening. Wear gloves when possible. Note time of injury.

# Bleeding
Direct pressure with clean cloth for at least 10 minutes without peeking. Elevate the limb if no fracture is suspected. Tourniquet only for life-threatening limb bleeding that won't stop — note the time applied.

# Shock
Pale, cold, clammy skin; fast weak pulse; confusion. Lay flat, keep warm, elevate legs if no spinal injury. Do not give food or drink if they may need surgery.

# Hypothermia
Shivering → confusion → unconsciousness. Get out of wind and wet clothes. Insulate from ground. Warm core first (chest, neck, armpits) with body heat or dry layers. Warm drinks only if fully awake.

# Fractures & sprains
Immobilize in the position found. Splint joint above and below. Ice 20 minutes on, 20 off if available. Do not straighten an obvious deformity.

# Burns
Cool with clean water 10–20 minutes. Cover loosely. Do not pop blisters. Seek help for face, hands, genitals, or burns larger than the victim's palm.

# Bites & stings
Wash well. Remove stinger by scraping, not squeezing. Watch for allergic reaction (swelling of face/throat, trouble breathing) — treat as emergency.

# When to evacuate
Chest pain, trouble breathing, head injury with vomiting or confusion, uncontrolled bleeding, snake bite with worsening swelling, any loss of consciousness.""",
    ),
    (
        "shelter-building",
        "Shelter building",
        """# Priorities
1. Location — dry ground, away from dead trees and flood paths; use natural windbreaks
2. Insulation from ground — boughs, pad, or pack under you (ground steals heat fast)
3. Wind and rain shell — tarp or debris roof with steep pitch
4. Ventilation — small opening high up reduces condensation; never seal a hot fire inside

# Tarp setups (fast)
**A-frame:** ridge line between two trees; tarp draped and pegged low on windward side.
**Lean-to:** high line on windward, low pegs on lee — good with fire reflector wall.
**Diamond / plough point:** one corner to ground as door, three pegged out — quick solo shelter.

# Debris hut (cold, no tarp)
Long ridge pole on low fork; ribs close together; pile leaves and boughs arm-deep. Door plug of backpack or boughs. Body heat warms a small space — keep it just big enough to lie in.

# Snow cave / trench
Only where snow is deep and stable. Vent hole mandatory. Mark entrance for rescuers.

# Cold nights
Dry layers inside sleeping bag. Hat and dry socks. Hot water bottle at feet if safe. Eat before sleep — calories are fuel.""",
    ),
    (
        "edible-plants",
        "Edible plants — cautious foraging",
        """# Golden rules
- **Identify with certainty** — when in doubt, do not eat
- Learn **poisonous look-alikes** in your region (see poisonous-plants page)
- Forage away from roads, trails, and treated lawns
- Take a little; leave most for wildlife and regrowth

# Universal edibles (verify locally)
**Dandelion** — entire plant edible when young; bitter leaves better blanched.
**Cattail** — young shoots peeled; pollen in early summer; roots starchy (cook).
**Berries you know** — blackberry/raspberry family; avoid white, yellow, or single berries on unknown plants unless expert ID.
**Pine** — inner bark and needles as tea (vitamin C); not all conifers are safe (avoid yew).
**Acorns** — leach tannins in repeated water changes before eating.

# Preparation
Most wild greens and roots need cooking. Test one small portion if first time — wait several hours for reaction.

# Regional note
This page is a starter. Add local species pages for your camp — photos and season matter.""",
    ),
    (
        "poisonous-plants",
        "Poisonous plants — avoid",
        """# Why this matters
Many edible plants have toxic look-alikes. Symptoms range from rash to organ failure. Teach children: **do not taste unknown plants**.

# Common hazards (North America–oriented; extend for your region)
**Poison ivy / oak / sumac** — "leaves of three, let it be"; urushiol oil causes blistering rash; wash skin and clothes after contact.
**Water hemlock** — often near wet areas; parsley-like; extremely deadly — mistaken for wild carrot.
**Death camas** — onion/garlic look-alike without onion smell; bulbs toxic.
**Foxglove** — tall spikes of tubular flowers; heart toxin.
**Nightshade berries** — shiny black or red berries on weedy plants; GI and neurological effects.
**Mushrooms** — no simple field rule; **never eat wild mushrooms without expert ID**.

# First response
Do not induce vomiting unless poison control advises. Save a sample for ID. Note time and amount. Seek medical help; use Beacon if remote.""",
    ),
    (
        "animal-sign",
        "Animal tracks & sign",
        """# Reading sign
Tracks show **who**, **when**, and **where**. Combine with scat, hair, rubs, and feeding sign.

# Track basics
Count toes and note claws. Measure width and length. Note gait: direct register (cat, fox) vs offset (deer, canine family).

# Common patterns
**White-tailed deer** — heart-shaped hooves, dew claws show in soft mud or when running.
**Canine (dog, coyote, fox)** — four toes, claw marks; coyote more oval and tidy than domestic dog.
**Feline (bobcat, cougar)** — four toes, **no claw marks** (retractable); round overall.
**Rabbit** — hind feet much larger; often in pairs.
**Bear** — five toes, large plantigrade foot; claws long and visible.

# Scat clues
Herbivore pellets vs carnivore twisted ropes with hair/bone. Freshness: color, moisture, insect activity.

# Safety
Large predator sign near camp — store food in bear-safe manner; make noise on trails; do not approach young animals.""",
    ),
    (
        "wayfinding",
        "Wayfinding & land navigation",
        """# Map & compass
Set **declination** for your map year and region. Orient map to ground using compass or known landmarks.

**Take a bearing:** map bearing → add/subtract declination → shoot azimuth in field.
**Follow a bearing:** pick a landmark on the line; walk to it; repeat (easy to drift in woods).

# Pace count
Measure how many steps ≈ 100 m on flat ground. Track distance on legs between checks.

# Without compass
**Sun** — northern hemisphere: sun at local solar noon is roughly south (shorter shadow points north). Watch shadow tip move over 15–20 min — arc points east–west.
**Stars** — find Polaris (Big Dipper pointer stars) for north.
**Terrain & water** — valleys lead to streams; ridges give views; moss is **not** reliable for direction alone.

# GPS failure plan
Always carry map and compass where terrain is serious. Mark camp on map before leaving. Tell someone your route and return time.""",
    ),
    (
        "kayaking",
        "Kayaking — safety & on-water navigation",
        """# Before launch
Check weather, wind, and water temperature. Cold water kills faster than air temp suggests — wear PFD always; consider wet suit below ~15 °C.

File a **float plan**: where launching, route, return time, who to call.

# PFD & gear
Whistle on PFD. Bilge pump or sponge. Spare paddle if touring. Light if near dusk.

# Entry & exit
Lowest dock point; paddle-bridge for unstable shore. Three points of contact.

# Strokes (basics)
**Forward** — torso rotation, not arms only.
**Sweep** — wide arc to turn.
**Draw** — pull paddle toward hip to move sideways.
**Brace** — low slap to prevent capsize.

# Navigation on water
Align map heading with shoreline features. Watch back bearings to return. Wind and current set you sideways — aim **up-current/up-wind** of target.

# Capsize
Stay with boat if possible. Self-rescue or wet exit practice in calm water before trips. Signal with whistle three blasts.

# Hazards
Strainers (downed trees), dams, motor traffic lanes, lightning — get off water early.""",
    ),
    (
        "water-purification",
        "Water — finding & making it safe",
        """# Finding water
Follow animal trails downhill, listen for flow, look for green vegetation in valleys. Morning dew and solar stills yield small amounts only.

Avoid stagnant pools with algae scum unless emergency — higher treatment burden.

# Clear vs safe
Clear water can still carry viruses, bacteria, protozoa (Giardia, Cryptosporidium).

# Treatment methods
**Boiling** — rolling boil 1 minute (3 at high altitude) — kills pathogens; does not remove chemicals.
**Filter** — 0.2 µm or smaller for bacteria/protozoa; **viruses** need chemical/UV/boil in many regions.
**Chemical** — follow label; wait time matters; cold water needs longer.
**UV pens** — clear water only; battery dependent.

# Best practice in camp
Designate fill point upstream of activity. Label treated vs raw containers.""",
    ),
    (
        "fire-craft",
        "Fire starting & camp stoves",
        """# Fire triangle
Heat, fuel, oxygen. Prepare **all sizes** before spark: tinder (bald eagle feather sticks, birch bark, dry grass), kindling (pencil-thick), fuel (thumb-thick up).

# Lay (wet conditions)
Platform of logs or bark off ground. Base of dry splits from inside dead standing wood. Lean-to or teepee over tinder bundle.

# Ignition
Matches in waterproof case; ferro rod with fine tinder; lens in bright sun. Protect flame from wind with cupped hands or body.

# Maintaining
Feed gradually; don't smother. Log cabin for cooking coals; teepee for quick warmth.

# Leave no trace
Use established rings where allowed. Fully extinguish: drown, stir, feel with back of hand. Pack out trash — foil and glass don't burn clean.

# When fire is banned
Use stove on mineral soil; check local restrictions.""",
    ),
]
