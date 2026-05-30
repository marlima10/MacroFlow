import tkinter as tk


def render_timeline(canvas, events, dark):
    canvas.delete("all")

    bg = "#050505" if dark else "#f2f4f8"
    text_color = "#ffffff" if dark else "#111827"
    muted_color = "#d7d7d7" if dark else "#4b5563"
    line_color = "#a3a3a3" if dark else "#6b7280"
    key_color = "#8f1237"
    mouse_color = "#111111" if dark else "#ffffff"
    mouse_outline = "#f4f4f5" if dark else "#111827"

    canvas.configure(bg=bg)
    visible_events = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("type") in ("key", "mouse_click", "mouse_scroll")
    ]

    if not visible_events:
        canvas.create_text(
            24,
            58,
            anchor="w",
            text="Grave uma macro para ver os eventos aqui.",
            fill=muted_color,
            font=("Segoe UI", 11),
        )
        canvas.configure(scrollregion=(0, 0, 760, 116))
        return

    x = 22
    center_y = 58
    previous_t = 0.0

    for position, (_index, event) in enumerate(visible_events):
        current_t = float(event.get("t", 0))
        if position > 0:
            x = draw_delay(canvas, x, center_y, current_t - previous_t, text_color, muted_color, line_color)

        if event.get("type") == "mouse_click":
            draw_mouse_icon(canvas, x, center_y, event.get("button", "left"), bool(event.get("pressed", True)), mouse_color, mouse_outline)
            x += 36
        elif event.get("type") == "mouse_scroll":
            draw_scroll_icon(canvas, x, center_y, mouse_color, mouse_outline)
            x += 36
        else:
            x = draw_key_event(canvas, x, center_y, event, key_color, text_color)

        previous_t = current_t

    canvas.configure(scrollregion=(0, 0, max(x + 40, 760), 116))


def draw_delay(canvas, x, center_y, seconds, text_color, muted_color, line_color):
    amount, unit = format_delay(max(0, seconds))
    canvas.create_line(x, center_y, x + 36, center_y, fill=line_color, width=1)
    canvas.create_text(x + 18, center_y - 16, text=amount, fill=text_color, font=("Segoe UI", 8, "bold"))
    canvas.create_text(x + 18, center_y + 2, text=unit, fill=muted_color, font=("Segoe UI", 7))
    return x + 48


def draw_key_event(canvas, x, center_y, event, key_color, text_color):
    label = timeline_key_label(event)
    box_width = max(26, min(74, 18 + len(label) * 8))
    rounded_rect(canvas, x, center_y - 16, x + box_width, center_y + 16, 4, fill=key_color, outline=key_color)
    canvas.create_text(x + box_width / 2, center_y, text=label, fill="#ffffff", font=("Segoe UI", 8, "bold"))

    triangle_y = center_y - 28 if bool(event.get("pressed", True)) else center_y + 28
    draw_triangle(canvas, x + box_width / 2, triangle_y, bool(event.get("pressed", True)), text_color)
    return x + box_width + 10


def format_delay(seconds):
    if seconds >= 1:
        return (f"{seconds:.1f}", "s")
    return (str(int(round(seconds * 1000))), "ms")


def timeline_key_label(event):
    key = event.get("key", {})
    if key.get("kind") == "char":
        value = key.get("value") or ""
        return value.upper() if len(value) == 1 else value

    value = key.get("value", "")
    names = {
        "space": "Space",
        "enter": "Enter",
        "shift": "Shift",
        "shift_r": "Shift",
        "ctrl": "Ctrl",
        "ctrl_l": "Ctrl",
        "ctrl_r": "Ctrl",
        "alt": "Alt",
        "alt_l": "Alt",
        "alt_r": "Alt",
        "tab": "Tab",
        "backspace": "Back",
        "esc": "Esc",
    }
    return names.get(value, value.replace("_", " ").title())


def rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_triangle(canvas, x, y, pressed, color):
    if pressed:
        points = (x, y - 4, x - 5, y + 3, x + 5, y + 3)
    else:
        points = (x, y + 4, x - 5, y - 3, x + 5, y - 3)
    canvas.create_polygon(points, fill=color, outline=color)


def draw_mouse_icon(canvas, x, center_y, button, pressed, fill, outline):
    top = center_y - 22
    bottom = center_y + 22
    canvas.create_oval(x + 4, top, x + 24, bottom, outline=outline, width=2, fill=fill)
    canvas.create_line(x + 14, top + 5, x + 14, top + 15, fill=outline, width=1)

    if button == "left":
        canvas.create_arc(x + 4, top, x + 24, top + 22, start=90, extent=90, outline=outline, width=3 if pressed else 1)
    elif button == "right":
        canvas.create_arc(x + 4, top, x + 24, top + 22, start=0, extent=90, outline=outline, width=3 if pressed else 1)
    else:
        canvas.create_oval(x + 11, top + 8, x + 17, top + 16, outline=outline, width=2, fill=outline if pressed else fill)


def draw_scroll_icon(canvas, x, center_y, fill, outline):
    draw_mouse_icon(canvas, x, center_y, "middle", False, fill, outline)
    canvas.create_line(x + 14, center_y - 8, x + 14, center_y + 8, fill=outline, width=2, arrow=tk.LAST)

