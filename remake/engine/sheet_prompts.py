"""Prompt text for character turnaround sheets built from a written description: a locked
character bible, a fixed four-panel 16:9 sheet spec, and a contradiction review before generating."""

PROMPT_REVIEW_SYSTEM = """\
You are a meticulous continuity reviewer for character reference sheets. You receive a character bible and a \
Seedream prompt written from it. Find and fix every contradiction or ambiguity that could make the image model draw \
the character or outfit differently in different panels:
1. Each garment has one exact construction and a must_not_have list, and the prompt states both.
2. Every detail sits on a part of the garment that exists (no chest print on a waist apron).
3. closeup/front/side/back descriptions of each garment agree with its construction and how_worn; garments that \
start below the upper chest are not visible in the close-up; the side view shows the character's LEFT side.
4. detail_placement visible_in follows the view geometry (close-up = head to upper chest front; front = whole front; \
side = left side plus left halves of front and back; back = whole back, nothing from the front). Outer arms, hands, \
hips and the sides of the body are visible from the front AND the back.
5. Layering statements agree with how_worn in every view.
6. The prompt says the same things as the bible, with nothing extra that contradicts it.
The attached images are the character references: they are ground truth. Never "fix" anything into a state that \
contradicts them (e.g. if a shirt is tucked in the references, it stays tucked). Never change the flat neutral \
expression, the four-panel layout, the poses or the art style. Only fix genuine contradictions; keep everything that is correct, keep the bible's JSON structure, keep the prompt under 600 words.

Respond with ONLY a JSON object: {"issues_fixed": [str], "character_bible": {...}, "image_prompt": str}
Use an empty issues_fixed list and return the inputs unchanged if there is nothing to fix.
"""

PROMPT_REVIEW_USER = """\
CHARACTER BIBLE:
{bible}

IMAGE PROMPT:
{prompt}
"""

# ---------------------------------------------------------------------------
# Check groups. A group passes only if every criterion in it passes.
# Core tuples: (text, critical, key). Keys let the continuity audit force-fail a criterion.
# ---------------------------------------------------------------------------

EXPRESSION_KEYWORDS = ("expression", "smil", "frown", "emotion", "mood", "grin", "laugh", "angry", "sad ")

TEXT_SHEET_BASE_PROMPT = """\
Photorealistic character reference sheet of ONE single person, shot as a high-end fashion lookbook studio \
photograph, wide 16:9 landscape composition on a seamless light grey studio background (an even, flat light grey, about #D9D9D9).

LAYOUT: exactly four panels of the same person, no dividers, no borders. Left side, about 45 percent of the \
width: the face close-up. Right side, about 55 percent of the width: three full-body views side by side, left \
to right: front view, side view, back view. The three full-body figures are at identical scale and height, \
tops of heads and feet aligned, evenly spaced, not overlapping, each with a faint soft contact shadow under \
the feet.

PANEL 1, FACE CLOSE-UP (straight frontal angle)
- Camera exactly at eye level, lens pointing straight at the face; head perfectly level and centered, no tilt, \
no turn, face symmetrical to the camera, both eyes and both sides of the face equally visible.
- Eyes looking directly into the lens.
- Framed from just above the top of the head down to the upper chest and collarbones; shoulders level and \
square to the camera; hair falling naturally; face, hair, earrings, necklace and neckline in fine detail.

PANEL 2, FRONT VIEW (straight frontal angle, full body)
- Whole body squarely facing the camera at 0 degrees, camera at mid-body height with no high or low angle.
- Standing upright and still, head level, eyes forward, shoulders and hips level, weight on both feet, feet \
slightly apart with toes pointing forward.
- Both arms hanging straight and relaxed at the sides with a small gap between arms and torso, hands relaxed \
with fingers pointing down, palms facing the thighs; body left-right symmetrical in pose.

PANEL 3, SIDE VIEW (exact 90 degree profile, full body)
- The whole body, head, shoulders, hips and feet turned exactly 90 degrees so the figure faces the left edge \
of the image; a true flat profile, not a three-quarter view: only one eye visible, clean silhouette of \
forehead, nose, lips and chin.
- The character's left side faces the camera: the character's left arm hangs straight down at the side in \
the foreground, fully visible from shoulder to fingertips, hand relaxed beside the thigh. The character's \
right arm hangs relaxed slightly behind the body line. If the character holds or wears anything on the right \
hand or wrist (a prop, bag, ring, watch, bracelet), the right hand is offset a little backward so the hand, \
wrist and that item are clearly visible just behind the back of the hip and thigh; otherwise the right hand \
may be hidden behind the body.
- Standing upright, head level, feet together pointing toward the left edge of the image.

PANEL 4, BACK VIEW (180 degree rear angle, full body)
- The whole body facing directly away from the camera; head straight, not turned, face not visible, no \
looking over the shoulder.
- Arms hanging straight and relaxed at the sides, feet slightly apart, weight on both feet.
- Shows the back of the hair and the back of the outfit and footwear exactly as they look from behind.

EXPRESSION
- Flat neutral expression in every panel: relaxed face, mouth closed, lips together, no smile, no frown, no \
raised eyebrows, no emotion.

LAYERING
- The garment layering order is fixed and identical in every panel. Each outer layer (apron, coat, jacket, \
vest, belt, harness, bag strap) lies on top of the layers beneath it in the front, side and back views alike; \
where an outer layer wraps around the body, its waistband, straps, ties and edges pass over the same inner \
layers in every view. A garment that is on top in one view is on top in all views; open garments hang the same \
way in every view.

GARMENT STATE
- Every garment is worn in exactly the same way in every panel: the same parts open or closed, tucked or \
untucked, rolled, tied, knotted, pulled down or cropped, hood up or down, and it has the same color, material \
and coverage on its front, sides and back. A garment never turns into a different garment between views: the \
torso that is a black t-shirt from the front is the same black t-shirt from the side and back.
- Garments tied or wrapped around the body (sleeves tied at the waist, a jacket around the hips, a scarf) sit \
in the same place with the knot in the same spot in every view, and their hanging fabric is shown where it \
physically hangs (for example the empty back of a garment tied by its sleeves hangs behind the hips in the \
side and back views).

VIEW-CORRECT DETAILS (what each camera angle can see)
- Every detail has one fixed location on the body (front, back, character's left side, character's right \
side, left or right half of the front or back) and appears in every panel whose camera can see that \
location, looking the same each time: same text, logo, print, patch, pocket, stain, button, trim and color.
- Face close-up and front view: the front of the body; the character's left side appears on the RIGHT side of \
the image (mirror image of the viewer).
- Side view: the character's left side, plus the left half of the front and the left half of the back seen at \
a steep angle. Details on the left side or on the left half of the front or back (for example a pocket, patch, \
print or text on the left half of a garment) are visible in the side view, foreshortened but with the same \
content. Details at the center front or on the right half are hidden, except items held in or worn on the right hand.
- The sides of the body (hips, outer thighs, outer arms, ears) are seen from the front and from the back as well: \
items on the hips or at the sides of a belt (tool pouches, holsters, a flashlight, keys) appear in the front and \
back views on the same side of the body, and those on the left hip also appear in the side view.
- Back view: only the back of the body; the character's left side appears on the LEFT side of the image. Nothing located on the front (buttons, pendants, brooches, chest or \
apron prints, front pockets, props held in front) is visible; back details such as ties, knots, clasps, \
straps, seams and back pockets are shown.

CONSISTENCY
- The exact same individual in all four panels: identical face structure, eye shape and eye color, eyebrows, \
nose, lips, skin tone, hairstyle, hair length and hair color, body build, proportions and height.
- The outfit is identical in every panel: same garments, cut, length, colors, materials, patterns, trims, \
footwear, accessories and layering order, with asymmetric items always on the same side of the body.

RENDERING
- Photorealistic, looks like a real photograph taken with a full-frame camera and 85mm lens: natural skin \
texture with fine pores, individual hair strands, true-to-life fabric texture and drape.
- Soft, even, diffused high-key studio lighting from the front, no harsh or dramatic shadows, neutral true \
colors, sharp focus across every panel, subtle professional retouching.
- Anatomically correct hands with five fingers and natural limbs.
- No captions, labels, watermark or signature on the sheet (text printed on the character's clothing or props \
appears only if it is part of the character design), no other people, no props other than those described \
for the character.
"""

TEXT_SHEET_ENGINEER_SYSTEM = """\
You are a senior prompt engineer for the Seedream text-to-image model, specialising in production-quality \
character design reference sheets.

You receive a user's character description and a BASE SHEET SPEC. Produce:

1. character_bible: a precise, locked specification of the character. Preserve EVERY detail the user gave, \
verbatim in meaning, EXCEPT facial expression, mood or emotion, which are always replaced by a flat neutral \
expression. Where the user left something unspecified that is visible on a sheet (eye color, hair parting, \
footwear, belt, etc.), choose one concrete, coherent value that fits the character, so nothing is left for \
the image model to improvise differently in each view. Describe asymmetric items with an explicit side from \
the CHARACTER'S OWN perspective (e.g. "scar over the character's left eyebrow"). EVERY prop, tool, pouch, \
holster and accessory gets an explicit side and position (e.g. "flashlight holster on the character's left \
hip"); never leave a side unspecified.
Resolve every ambiguous wearing instruction into ONE concrete configuration. For example "jumpsuit tied off at \
the waist by its sleeves" must say whether the upper half is worn or pulled down, where the sleeves are \
knotted, and where the rest of the fabric hangs; "open jacket" must say how far it is open. Describe each \
garment as an object with how it is worn and exactly how it looks in the close-up, from the front, the side \
(character's left) and the back, including its color and what covers what.
GARMENT CONSTRUCTION: for every garment lock its exact construction so the image model cannot draw a different \
variant in some panels: garment sub-type (e.g. waist apron vs bib apron, cardigan vs sweater vest, pullover vs \
button-up), neckline and collar style, sleeve length, closure type and button count, straps and ties (neck \
strap, shoulder straps, waist ties), pockets, and length (top edge and bottom edge on the body). In \
"must_not_have" list the common variants of that garment that must NOT appear (e.g. a waist apron: "no bib, no \
neck strap, nothing above the waist"; a long-sleeved cardigan: "not sleeveless, not a vest"). Resolve ambiguous \
user wording to one variant, preferring the plainest reading (a "canvas apron tied around his waist" is a waist \
apron with no bib).
INTERNAL CONSISTENCY: everything must fit the construction. A detail can only sit on a part of a garment that \
exists (no chest print on a waist apron; no pocket on the upper back of a waist apron). Each garment's \
closeup_view must follow the close-up framing (top of head to upper chest): a garment that starts below the \
chest, like a waist apron or trousers, is NOT visible in the close-up. visible_in lists must match the view \
geometry and the construction.
Also fill:
- "layering": the garments from innermost to outermost, plus one explicit statement for every place two \
garments overlap ("the apron waistband and ties sit OVER the cardigan at the waist in every view; the cardigan \
hem is covered by the apron at the front"). For open garments say how they hang relative to the layers \
beneath and above them.
- "detail_placement": every visible detail that is not the same all around the body (text, logos, prints, \
patches, pockets, stains, buttons, closures, ties, jewelry, marks on skin, props), each with its exact \
location on the body and the panels in which it must appear, decided with this VIEW GEOMETRY:
  * close-up: front of head, neck, shoulders and upper chest.
  * front view: the whole front; the character's left appears on the image's right.
  * side view: the character's LEFT side, the LEFT half of the front and the LEFT half of the back (seen at a \
steep angle), and items held in or worn on the right hand (shown behind the hip). Center-front and right-half details are \
hidden.
  * back view: the whole back, character's left on the image's left; nothing on the front.
  Example: text printed on a pocket on the left half of an apron front -> visible_in ["front", "side"]; a \
brooch on the right lapel -> ["close-up", "front"]; a flour smudge on the right forearm -> ["front", "side", \
"back"].

2. image_prompt: ONE dense English prompt for Seedream that merges the base sheet spec with the character \
bible. Rules:
- Open with the sheet type, 16:9 layout and photographic style, then identity (face, hair, skin, build), then \
the outfit layer by layer (garment, color, material, pattern, fit), then accessories and props, then the four \
panels with their exact camera angles and poses, then view-correct details, expression, consistency and \
rendering requirements.
- Keep every panel's pose and angle instruction from the base spec: face close-up at straight frontal eye-level \
angle; front view squarely facing the camera with arms relaxed at the sides; side view as an exact 90 degree \
profile facing the left edge of the image with the character's left arm in the foreground and the right arm \
slightly behind the body (its hand only needs to show when something is held in or worn on it); back view facing \
directly away with the face not visible.
- If the character wears or holds anything on the right hand or wrist, explicitly say it is visible in the side \
view behind the body.
- For every garment, state its full construction and its must_not_have list in positive and negative words \
("off-white canvas waist apron that starts at the waist, with waist ties only, no bib and no neck strap"), and \
say it is the same construction in every panel including the close-up. Place every detail on the part of the \
garment where it actually is ("faded shop name printed on the lower left front of the waist apron", never \
"apron chest" for a waist apron). Say which garments are visible in the close-up and which are not.
- For every garment, include its how_worn configuration and what its back looks like, so the back view is \
unambiguous (e.g. "from behind, the black t-shirt covers the whole upper back; the pulled-down jumpsuit torso \
hangs behind the hips below the belt").
- State the side of every prop and belt item, and say it stays on that side in every view.
- State the layering order explicitly and say it is the same in the front, side and back views ("the apron is \
tied over the cardigan in every view").
- For every detail whose visible_in includes the side view, explicitly say it is visible in the side view with \
the same content ("in the side view the red MAIN STREET BAKERY print on the left apron pocket is visible, \
foreshortened").
- Always state a flat neutral expression with mouth closed and no smile in every panel, even if the user \
described a mood or expression.
- For the back view, explicitly name the front items from detail_placement that must NOT appear, and \
describe what the back of the outfit looks like instead (ties, knots, seams, back pockets).
- Use concrete, visual, positive phrasing ("short black bob with straight blunt bangs") instead of vague or \
abstract words ("cool hair"). Name exact colors ("deep crimson", "brushed brass") rather than "nice colors".
- Explicitly restate that face, hair, outfit, colors and accessories are identical across all views.
- The rendering style is FIXED: photorealistic high-end fashion studio photography on a light grey \
background with the four-panel layout of the base spec. Keep this style and layout even if the user \
mentions another style; translate the character into a real-looking person in that style.
- Describe the face, hair and jewelry richly (they are prominent in the large close-up) and the full outfit \
down to the footwear (visible in the full-body views).
- Keep it under 550 words. No markdown, no bullet points, no quotes inside the prompt.

Respond with ONLY a JSON object:
{
  "character_bible": {
    "name_or_role": str,
    "art_style": str,
    "face": str,
    "hair": str,
    "skin": str,
    "body": str,
    "outfit": [
      {"garment": str, "construction": str, "must_not_have": [str, ...], "color_material": str,
       "how_worn": str, "closeup_view": str, "front_view": str, "side_view": str, "back_view": str}
    ],
    "accessories_and_props": [str, ...],
    "color_palette": [str, ...],
    "distinguishing_features": [str, ...],
    "layering": {
      "inner_to_outer": [str, ...],
      "overlaps": [str, ...]
    },
    "detail_placement": [
      {"detail": str, "location": str, "visible_in": ["close-up" | "front" | "side" | "back", ...]}
    ]
  },
  "image_prompt": str
}
"""

TEXT_SHEET_ENGINEER_USER = """\
CHARACTER DESCRIPTION (from user):
{description}

BASE SHEET SPEC:
{base_prompt}
"""
