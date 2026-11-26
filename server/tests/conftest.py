import pytest

from cadskill_mcp.runner import Runner


@pytest.fixture(scope="session")
def runner():
    r = Runner()
    yield r
    r.stop()


PLATE = '''
LENGTH, WIDTH, THICKNESS = 40, 24, 6
CORNER, HOLE = 4, 8
plate = (cq.Workplane("XY").box(LENGTH, WIDTH, THICKNESS)
         .edges("|Z").fillet(CORNER)
         .faces(">Z").workplane().hole(HOLE))
show_object(plate, name="plate")
'''

TWO = PLATE + '''
post = cq.Workplane("XY").circle(5).extrude(20).translate((30, 0, 0))
show_object(post, name="post", options={"color": "red"})
'''


@pytest.fixture
def plate():
    return PLATE


@pytest.fixture
def two():
    return TWO
