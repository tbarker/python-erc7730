"""Reference-only template syntax shared by authoring and descriptor validation."""

from collections.abc import Callable


def translate_template(
    text: str,
    resolve: Callable[[str], str],
    *,
    natspec: bool,
    literal_backticks: bool = False,
) -> str:
    """Translate references only, without executing NatSpec expressions.

    NatSpec uses backticks and treats braces as prose. Explicit ERC-7730 templates
    use braces and double braces for escaping. Neither form is truncated.
    """
    result: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if natspec:
            if character == "`":
                end = text.find("`", index + 1)
                if end == -1:
                    raise ValueError("unclosed NatSpec expression")
                result.append("{" + resolve(text[index + 1 : end].strip()) + "}")
                index = end + 1
            else:
                result.append(character * 2 if character in "{}" else character)
                index += 1
        elif text[index : index + 2] in ("{{", "}}"):
            result.append(text[index : index + 2])
            index += 2
        elif character == "{":
            end = text.find("}", index + 1)
            if end == -1:
                raise ValueError("unclosed ERC-7730 placeholder")
            result.append("{" + resolve(text[index + 1 : end].strip()) + "}")
            index = end + 1
        elif character == "}" or (character == "`" and not literal_backticks):
            raise ValueError("unexpected template delimiter; custom templates use {path} and {{literal braces}}")
        else:
            result.append(character)
            index += 1
    return "".join(result)
