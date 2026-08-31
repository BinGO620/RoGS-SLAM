from rich.console import Console

_log_styles = {
    "MonoGS": "bold green",
    "GUI": "bold magenta",
    "Eval": "bold red",
}


def get_style(tag):
    if tag in _log_styles.keys():
        return _log_styles[tag]
    return "bold blue"


def Log(*args, tag="MonoGS"):
    style = get_style(tag)
    Console(no_color=True).print(f"[{style}]{tag}:[/{style}]", *args)
