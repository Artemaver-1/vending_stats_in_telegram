from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from html import escape

from markupsafe import Markup

from app.formatting import rub


@dataclass(frozen=True, slots=True)
class Series:
    name: str
    values: Sequence[Decimal]
    css_class: str


class BarChart:
    """Grouped bar chart rendered to inline SVG, so the Mini App needs no charting library.

    Colours come from CSS classes and therefore follow the Telegram theme.
    """

    width = 340
    height = 160
    pad_top = 12
    pad_bottom = 22

    def __init__(self, labels: Sequence[str], series: Sequence[Series]) -> None:
        if any(len(s.values) != len(labels) for s in series):
            raise ValueError("every series needs a value per label")
        self.labels = labels
        self.series = series

    def render(self) -> Markup:
        values = [v for s in self.series for v in s.values] or [Decimal(0)]
        top = max(max(values), Decimal(0))
        bottom = min(min(values), Decimal(0))
        span = (top - bottom) or Decimal(1)
        plot_h = self.height - self.pad_top - self.pad_bottom

        def y(value: Decimal) -> float:
            return self.pad_top + float((top - value) / span) * plot_h

        zero = y(Decimal(0))
        slot = self.width / max(len(self.labels), 1)
        bar_w = slot * 0.7 / max(len(self.series), 1)

        parts = [
            f'<svg class="chart" viewBox="0 0 {self.width} {self.height}" role="img">',
            f'<line class="chart-axis" x1="0" x2="{self.width}" y1="{zero:.1f}" y2="{zero:.1f}"/>',
        ]
        for i, label in enumerate(self.labels):
            x0 = i * slot + slot * 0.15
            for j, s in enumerate(self.series):
                value = s.values[i]
                top_y, bottom_y = sorted((y(value), zero))
                height = max(bottom_y - top_y, 1 if value else 0)
                css = s.css_class + (" negative" if value < 0 else "")
                parts.append(
                    f'<rect class="{css}" x="{x0 + j * bar_w:.1f}" y="{top_y:.1f}" '
                    f'width="{bar_w - 1:.1f}" height="{height:.1f}" rx="2">'
                    f"<title>{escape(label)} · {escape(s.name)}: {rub(value)}</title></rect>"
                )
            parts.append(
                f'<text class="chart-label" x="{i * slot + slot / 2:.1f}" '
                f'y="{self.height - 6}" text-anchor="middle">{escape(label)}</text>'
            )
        parts.append("</svg>")
        return Markup("".join(parts))
