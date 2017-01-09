#!/usr/bin/env python3

"""A very, very simple thing to read an SVG and convert it to a list of cairo drawing instructions.
Will likely fail on your SVG."""

from gi.repository import Gio
from xml.dom import minidom
import sys
import cairo

class SVG2Cairo(object):
    IGNORE_ELEMENTS = ["defs", "metadata", "sodipodi:namedview"]

    def __init__(self, debug=False):
        self.svg_string = None
        self.debug = debug
        self.converted_result = None

    def set_svg_as_string_sync(self, svg_string):
        self.svg_string = svg_string

    def set_svg_as_filename_async(self, filename):
        # This function assumes you have a gtk mainloop running somewhere
        # so that Gio async stuff works.
        # if you don't, it'll probably hang and never finish.
        # so don't do that.
        f = Gio.File.new_for_path(filename)
        f.load_contents_async(None, self.finish_loading_file)
    
    def finish_loading_file(self, f, res):
        success, contents, _ = f.load_contents_finish(res)
        self.set_svg_as_string_sync(contents)

    def _to_rgba(self, hexcol):
        if hexcol == "none": return None
        if len(hexcol) == 7:
            return [int(hexcol[1:3], 16), int(hexcol[3:5], 16), int(hexcol[5:7], 16), 1]
        if self.debug:
            print("Unknown colour '%s'" % (hexcol,))

    def read_transform(self, transform_string):
        # Not at _all_ convinced that this works right.
        # If you can possibly avoid it, don't have transform attributes in your bubble SVGs.
        # In inkscape, a good way to avoid this is to not put anything in any groups at
        # all, including the layers. Just delete them. And save as simple SVG, not inkscape.
        v = transform_string.strip()
        if not v.startswith("matrix(") or not v.endswith(")"):
            if self.debug:
                print("Couldn't understand transform attribute '%s'" % (val,))
            return
        v = v[7:-1]
        try:
            parts = [float(x.strip()) for x in v.split(",")]
        except:
            if self.debug:
                print("Couldn't understand transform attribute '%s'" % (val,))
            return
        if len(parts) != 6:
            if self.debug:
                print("Couldn't understand transform attribute '%s'" % (val,))
            return
        return cairo.Matrix(*parts)

    def read_style(self, style_string):
        items = [x.strip() for x in style_string.split(";")]
        stroke = None
        fill = None
        line_width = None
        for i in items:
            prop, val = i.split(":", 2)
            if prop == "stroke":
                rgba = self._to_rgba(val)
                if rgba: stroke = rgba
            elif prop == "stroke-width":
                line_width = float(val)
            elif prop == "fill":
                rgba = self._to_rgba(val)
                if rgba: fill = rgba
        instructions = []
        if line_width:
            instructions.append(["set_line_width", [line_width]])
        if stroke:
            instructions.append(["set_source_rgba", stroke])
            if fill:
                stroke_cmd = "stroke_preserve"
            else:
                stroke_cmd = "stroke"
            instructions.append([stroke_cmd, []])
        if fill:
            instructions.append(["set_source_rgba", fill])
            instructions.append(["fill", []])
        if instructions:
            return instructions

    def expect(self, node, attrs):
        for a in attrs:
            if not node.hasAttribute(a):
                if self.debug:
                    print("Expected node <%s> to have attribute '%s'" % (node.nodeName, a))
                return False
        return True

    def parse_ellipse(self, node):
        # Cairo doesn't actually do ellipses, sigh.
        # What you have to do is set unequal x and y scales and then draw a circle.
        # Ha ha ha ha thanks for that Cairo. Thairo.
        # On the other hand, neat little ellipse drawing algorithm at
        # https://www.cairographics.org/documentation/pycairo/2/reference/context.html#cairo.Context.arc
        # so actually thanks for that, Cairo docs people.
        if not self.expect(node, ["cx", "cy", "rx", "ry"]): return
        cx = float(node.getAttribute("cx"))
        cy = float(node.getAttribute("cy"))
        rx = float(node.getAttribute("rx"))
        ry = float(node.getAttribute("ry"))

        ellipse_x = cx - rx
        ellipse_y = cy - ry
        ellipse_w = rx * 2
        ellipse_h = ry * 2

        instructions = []
        instructions.append(["save", []])
        instructions.append(["translate", [ellipse_x + ellipse_w / 2, ellipse_y + ellipse_h / 2]])
        instructions.append(["scale", [rx, ry]])
        instructions.append(["arc", [0.0, 0.0, 1.0, 0.0, 2 * 3.14159]]) # no partial ellipses here
        instructions.append(["restore", []])
        return instructions

    def parse_rect(self, node):
        if not self.expect(node, ["x", "y", "width", "height"]): return
        x = float(node.getAttribute("x"))
        y = float(node.getAttribute("y"))
        width = float(node.getAttribute("width"))
        height = float(node.getAttribute("height"))
        return [
            ["rectangle", [x, y, width, height]]
        ]

    def parse_path(self, node):
        if not self.expect(node, ["d"]): return
        d = node.getAttribute("d").split()
        instructions = []
        mode = None
        for item in d:
            if item == "M":
                mode = "move_to"
            elif item == "m":
                mode = "rel_move_to"
            elif item == "l":
                mode = "rel_line_to"
            elif item == "L":
                mode = "line_to"
            elif item == "Z" or item == "z":
                instructions.append(["close_path", []])
            elif mode == "move_to":
                parts = [float(x) for x in item.split(",")]
                instructions.append(["move_to", parts])
                mode = "line_to"
            elif mode == "rel_line_to":
                parts = [float(x) for x in item.split(",")]
                instructions.append(["rel_line_to", parts])
            elif mode == "line_to":
                parts = [float(x) for x in item.split(",")]
                instructions.append(["line_to", parts])
            else:
                if self.debug:
                    print("Confused by path instruction '%s' in path '%s'" % (item, d))
                return
        return instructions

    def convert(self):
        if self.converted_result: return self.converted_result
        dom = minidom.parseString(self.svg_string)
        instructions = []
        if not dom.documentElement.hasAttribute("viewBox"):
            raise Exception("No viewBox attribute on <svg>")
        viewBox = dom.documentElement.getAttribute("viewBox")
        try:
            x, y, width, height = viewBox.split()
        except:
            raise Exception("viewBox attribute ('%s') was too complex for me" % (viewBox,))
        if x != "0" or y != "0":
            raise Exception("viewBox attribute ('%s') was too complex for me" % (viewBox,))
        try:
            width = float(width)
            height = float(height)
        except:
            raise Exception("viewBox attribute ('%s') was too complex for me (strange width/height)" % (viewBox,))

        nodelist = dom.documentElement.getElementsByTagName("*")
        for c in nodelist:
            if c.nodeType == 1:
                if c.nodeName in self.IGNORE_ELEMENTS: continue
                handler = getattr(self, "parse_" + c.nodeName, None)
                if handler:
                    result = handler(c)
                    if type(result) is type([]):
                        style_result = None
                        transform = None
                        if c.hasAttribute("style"):
                            style_result = self.read_style(c.getAttribute("style"))
                        if c.hasAttribute("transform"):
                            transform = self.read_transform(c.getAttribute("transform"))
                        if transform:
                            instructions.append(["save", []])
                            instructions.append(["multiply_by_matrix", [transform]])
                        instructions += result
                        if style_result:
                            instructions += style_result
                        if transform:
                            instructions.append(["restore", []])
                else:
                    if self.debug:
                        print("Unknown SVG element <%s>" % (c.nodeName,))
        self.converted_result = {"width": width, "height": height, "instructions": instructions}
        return self.converted_result

    def render_to_context_at_size(self, context, x, y, width, height):
        """Renders this SVG inside a box of max-size width x height at 0,0
           This preserves aspect ratio.
        """
        # We scale the image down to fit in the requested box.
        # However, this means that we want to scale line_width UP, because
        # we want line_widths to always be the same width as the original image
        # specifies, no matter how big or small the image is.
        # This avoids the problem that making a speech bubble smaller also
        # makes its borders thinner.

        result = self.convert()

        # stash the current context so we can put it back at the end
        context.save()

        # scale the context matrix so we fit in the required box
        width_scale = width / result["width"]
        height_scale = height / result["height"]
        scale = min(width_scale, height_scale)
        context.translate(x, y)
        context.scale(scale, scale)

        for cmd, params in result.get("instructions", []):
            if self.debug: print (cmd, params)
            if cmd == "set_line_width":
                getattr(context, cmd)(params[0] * (1/scale))
            else:
                getattr(context, cmd)(*params)

        context.restore()
        return {"width": result["width"] * scale, "height": result["height"] * scale}

    def test_render(self, to_png):
        SCALE = 0.4
        result = self.convert() # call this here to get the width and height
        scale_w = int(result["width"] * SCALE)
        scale_h = int(result["height"] * SCALE)
        base = cairo.ImageSurface(cairo.FORMAT_ARGB32, scale_w, scale_h)
        ctx = cairo.Context(base)
        self.render_to_context_at_size(ctx, 0, 0, scale_w, scale_h)
        base.write_to_png(to_png)


if __name__ == "__main__":
    incoming_svg = sys.argv[1]
    outgoing_png = sys.argv[2]
    fp = open(incoming_svg)
    svg_string = fp.read().encode("utf-8")
    fp.close()
    c = SVG2Cairo(debug=True)
    c.set_svg_as_string_sync(svg_string)
    c.test_render(outgoing_png)
