"""app.py - a small program that records its work with our tracker."""
import random  # to make "add_sugar" fail some of the time
import time  # time.sleep() pretends each step takes real time

from opentelemetry import trace  # API to get a tracer
from opentelemetry.trace import Status, StatusCode  # used to mark a span as failed

from tracker import setup_tracing  # our function from tracker.py

# Turn tracing on ONCE at startup. "tea-shop" becomes the service name stored
# with every span, so you can tell which program produced it.
setup_tracing("tea-shop")
# A tracer is the object that creates spans. The name says which part of the code uses it.
tracer = trace.get_tracer("tea-shop")


def make_tea(kind: str) -> None:
    # start_as_current_span opens a span and makes it the "current" one.
    # Leaving the "with" block ends the span and hands it to our exporter.
    with tracer.start_as_current_span("make_tea") as span:
        # Attributes are key/value details attached to the span (shown later in the DB).
        span.set_attribute("tea.kind", kind)
        # Opened while make_tea is current, so it automatically becomes its CHILD.
        # That parent/child link is what view.py later draws as a tree.
        with tracer.start_as_current_span("boil_water") as s:
            s.set_attribute("water.ml", 250)
            time.sleep(0.2)  # pretend boiling takes 200 ms
        with tracer.start_as_current_span("steep_tea"):  # no "as" name: we don't need the span object
            time.sleep(0.1)  # 100 ms
        with tracer.start_as_current_span("add_sugar") as s:
            if random.random() < 0.3:  # ~30% chance: sometimes things go wrong
                # Mark this span as failed. view.py will print [ERROR] next to it.
                s.set_status(Status(StatusCode.ERROR, "out of sugar"))
            time.sleep(0.05)  # 50 ms
    # By here all four spans have ended and have been written to SQLite.


# Runs only when you execute "python app.py", not when another file imports it.
if __name__ == "__main__":
    make_tea("ceylon black")
    print("Done. Spans saved to traces.db - run: python view.py")
