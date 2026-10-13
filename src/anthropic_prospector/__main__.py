"""Allow `python -m anthropic_prospector`."""

from anthropic_prospector.cli import app

if __name__ == "__main__":
    app(prog_name="prospector")
