#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Gio, cairo
import math, os, codecs, sys, json, copy, glob
import svg2cairo

__VERSION__ = "0.1"

ALLOWED_FONTS = ["Impact", "Monospace", "Sans", "Serif"]

def in_rectangle(point, rect):
    if point.x > rect[0] and point.y > rect[1] and point.x < rect[0]+rect[2] and point.y < rect[1]+rect[3]:
        return True
    return False

class Main(object):

    ##################################################################
    # App and window setup
    ##################################################################

    def __init__(self):
        # useful globals
        #base = cairo.XMLSurface(cairo.FORMAT_ARGB32, self.snapsize[0] * self.zoomlevel, self.snapsize[1] * self.zoomlevel)

        self.resize_timeout = None
        self.window_metrics = None
        self.window_metrics_restored = False
        self.last_load_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        self.img = None

        # create application
        self.app = Gtk.Application.new("org.kryogenix.graven", 
            Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.app.connect("command-line", self.handle_commandline)

    def handle_commandline(self, app, cmdline):
        args = cmdline.get_arguments()[1:]
        options = [x for x in args if x.startswith("--")]
        nonoptions = [x for x in args if not x.startswith("--")]
        if hasattr(self, "w"):
            # already started
            if "--about" in options:
                self.show_about_dialog()
                if nonoptions:
                    self.show_image_path(nonoptions[0])
            return 0
        self.start_everything_first_time()
        if "--about" in options:
            self.show_about_dialog()
        if nonoptions:
            self.show_image_path(nonoptions[0])
        return 0

    def start_everything_first_time(self, on_window_map=None):
        GLib.set_application_name("Graven")

        # the window
        self.w = Gtk.ApplicationWindow.new(self.app)
        self.w.set_title("Graven")
        self.w.set_size_request(400, 400)
        self.w.connect("configure-event", self.window_configure)
        self.w.connect("destroy", Gtk.main_quit)
        if on_window_map: self.w.connect("map-event", on_window_map)

        # the headerbar
        head = Gtk.HeaderBar()
        head.set_show_close_button(True)
        #head.props.title = "Graven"
        self.w.set_titlebar(head)

        self.btncrop = Gtk.ToggleButton.new_with_label("Crop")
        head.pack_start(self.btncrop)
        self.btncrop.connect("clicked", self.crop)
        self.btncrop.set_sensitive(False)

        self.btnbubble = Gtk.MenuButton(label="Bubble")
        head.pack_start(self.btnbubble)
        self.btnbubble.set_sensitive(False)

        self.btnapply = Gtk.Button.new_with_label("Apply")
        head.pack_end(self.btnapply)
        self.btnapply.set_sensitive(False)

        self.empty = Gtk.Label()
        self.empty.set_markup('Paste or drag an image, or <a href="#">Open</a> a file')
        self.empty.connect("activate-link", self.open_file)
        self.w.add(self.empty)

        self.w.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        self.w.drag_dest_add_uri_targets()
        self.w.drag_dest_add_image_targets()
        self.w.connect("drag-data-received", self.on_drag_data_received)

        # and, go
        self.w.show_all()
        GLib.idle_add(self.load_state)
        GLib.idle_add(self.populate_bubble_menu)

    def populate_bubble_menu(self):
        bubble_menu_folders = [
            os.path.join(os.path.split(__file__)[0], "..", "bubbles"),
            os.path.join(GLib.get_user_data_dir(), "graven", "bubbles")
        ]
        bubble_files = []
        for f in bubble_menu_folders:
            if os.path.isdir(f):
                bubble_files += glob.glob(os.path.join(f, "*.bubble.svg"))
        if not bubble_files:
            self.btnbubble.destroy()
            return
        bubblemenu = Gtk.Menu.new()
        for f in bubble_files:
            mi = Gtk.MenuItem.new()
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(f, 100, 75)
            mimg = Gtk.Image.new_from_pixbuf(pb)
            mi.add(mimg)
            s2c = svg2cairo.SVG2Cairo()
            s2c.set_svg_as_filename_async(f) # this will load in the background
            mi.connect("activate", self.bubble_chosen, s2c)
            bubblemenu.append(mi)
        self.btnbubble.set_popup(bubblemenu)
        bubblemenu.show_all()
        if self.img:
            self.btnbubble.set_sensitive(True)
        else:
            self.btnbubble.set_sensitive(False)

    def on_drag_data_received(self, widget, drag_context, x,y, data, info, time):
        pb = data.get_pixbuf()
        if pb:
            print("Got a pixbuf")
            Gtk.drag_finish(drag_context, True, False, time)
            self.show_image_pixbuf(pb)
        else:
            uris = data.get_uris()
            if uris and len(uris) == 1:
                print("Got URIs", uris)
                self.show_image_uri(uris[0])
                Gtk.drag_finish(drag_context, True, False, time)
            else:
                print ("Got nothing")
                Gtk.drag_finish(drag_context, False, False, time)

    def open_file(self, lbl, uri):
        dialog = Gtk.FileChooserDialog("Please choose a file", self.w,
            Gtk.FileChooserAction.OPEN,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
             Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        dialog.set_current_folder(self.last_load_dir)

        filter_img = Gtk.FileFilter()
        filter_img.set_name("Image files")
        filter_img.add_pattern("*.png")
        filter_img.add_pattern("*.jpg")
        dialog.add_filter(filter_img)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.show_image_path(dialog.get_filename())
            self.last_load_dir = os.path.split(dialog.get_filename())[0]
            GLib.idle_add(self.serialise)
        elif response == Gtk.ResponseType.CANCEL:
            pass

        dialog.destroy()
        return True

    def show_about_dialog(self, *args):
        about_dialog = Gtk.AboutDialog()
        about_dialog.set_authors(["Stuart Langridge"])
        about_dialog.set_version(__VERSION__)
        about_dialog.set_license_type(Gtk.License.MIT_X11)
        about_dialog.set_website("https://www.kryogenix.org/code/graven")
        about_dialog.run()
        if about_dialog: about_dialog.destroy()

    ##################################################################
    # Persistence
    ##################################################################

    def window_configure(self, window, ev):
        if not self.window_metrics_restored: return
        if self.resize_timeout:
            GLib.source_remove(self.resize_timeout)
        self.resize_timeout = GLib.timeout_add_seconds(1, self.save_window_metrics,
            {"x":ev.x, "y":ev.y})

    def save_window_metrics(self, props):
        scr = self.w.get_screen()
        sw = float(scr.get_width())
        sh = float(scr.get_height())
        # We save window dimensions as fractions of the screen dimensions, to cope with screen
        # resolution changes while we weren't running
        self.window_metrics = {
            "wx": props["x"] / sw,
            "wy": props["y"] / sh
        }
        self.serialise()
        self.resize_timeout = None

    def restore_window_metrics(self, metrics):
        scr = self.w.get_screen()
        sw = float(scr.get_width())
        sh = float(scr.get_height())
        self.w.move(int(sw * metrics["wx"]), int(sh * metrics["wy"]))

    def get_cache_file(self):
        return os.path.join(GLib.get_user_cache_dir(), "graven.json")

    def serialise(self, *args, **kwargs):
        # yeah, yeah, supposed to use Gio's async file stuff here. But it was writing
        # corrupted files, and I have no idea why; probably the Python var containing
        # the data was going out of scope or something. Anyway, we're only storing
        # five small images, so life's too short to hammer on this; we'll write with
        # Python and take the hit.
        fp = codecs.open(self.get_cache_file(), encoding="utf8", mode="w")
        data = {}
        if self.window_metrics:
            data["metrics"] = self.window_metrics
        if self.last_load_dir:
            data["last_load_dir"] = self.last_load_dir
        json.dump(data, fp, indent=2)
        fp.close()

    def finish_loading_state(self, f, res):
        try:
            success, contents, _ = f.load_contents_finish(res)
            data = json.loads(contents.decode("utf-8"))
            metrics = data.get("metrics")
            if metrics:
                self.restore_window_metrics(metrics)
            self.window_metrics_restored = True
            if "last_load_dir" in data:
                self.last_load_dir = data.get("last_load_dir")
        except Exception as e:
            print("Failed to restore data")
            raise

    def load_state(self):
        if not os.path.exists(self.get_cache_file()): return
        f = Gio.File.new_for_path(self.get_cache_file())
        f.load_contents_async(None, self.finish_loading_state)

    ##################################################################
    # Actual function
    ##################################################################

    def show_image_uri(self, uri):
        f = Gio.File.new_for_uri(uri)
        self.show_image_path(f.get_path())

    def show_image_path(self, path):
        img = Gtk.Image.new_from_file(path)
        pb = img.get_pixbuf()
        self.show_image_pixbuf(pb)

    def show_image_pixbuf(self, pb):
        self.img = Gtk.Image.new_from_pixbuf(pb)
        self.show_image()

    def show_image(self):
        if self.img:
            print("showing image")
            self.w.remove(self.w.get_children()[0])
            self.fixed = Gtk.Fixed()
            self.fixed.add(self.img)
            self.w.add(self.fixed)
            self.fixed.show_all()
            self.btncrop.set_sensitive(True)
            self.btnbubble.set_sensitive(True)

    def crop(self, btn):
        if btn.get_active():
            self.draw_crop_mode()
        else:
            self.remove_crop_mode()

    def draw_crop_mode(self):
        alloc = self.fixed.get_allocation()
        self.da = Gtk.DrawingArea()
        self.da.set_size_request(alloc.width, alloc.height)
        self.da.set_events(Gdk.EventMask.BUTTON_MOTION_MASK | 
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.fixed.add(self.da)
        self.da.show_all()
        self.crop_apply_id = self.btnapply.connect("clicked", self.crop_apply)
        self.btnapply.set_sensitive(True)
        self.handle_rectangles = []
        self.crop_rectangle = (-1, -1, -1, -1)

        self.crop_borders = [[0.3,0.3], [0.75,0.55]]
        self.crop_mousedown_id = self.da.connect("button-press-event", self.crop_mousedown)
        self.crop_mouseup_id = self.da.connect("button-release-event", self.crop_mouseup)
        self.da.connect("draw", self.actually_draw_crop)
        self.da.queue_draw()

    def crop_apply(self, btn):
        pb = self.img.get_pixbuf()
        w = pb.get_width()
        h = pb.get_height()
        print("apply crop", self.crop_borders)

        sub_tl = (int(self.crop_borders[0][0] * w), int(self.crop_borders[0][1] * h))
        sub_br = (int(self.crop_borders[1][0] * w), int(self.crop_borders[1][1] * h))
        sub_w = int(sub_br[0] - sub_tl[0])
        sub_h = int(sub_br[1] - sub_tl[1])

        new_pb = GdkPixbuf.Pixbuf.new(pb.get_colorspace(), pb.get_has_alpha(), pb.get_bits_per_sample(), sub_w, sub_h)

        pb.copy_area(sub_tl[0], sub_tl[1], sub_w, sub_h, new_pb, 0, 0)

        self.remove_crop_mode()
        print("apply")
        self.show_image_pixbuf(new_pb)

    def actually_draw_crop(self, da, context):
        surface = context.get_target()
        w = surface.get_width()
        h = surface.get_height()
        context.set_source_rgba(0, 0, 0, 0.6)
        context.set_line_width(3)

        tlx = self.crop_borders[0][0] * w
        tly = self.crop_borders[0][1] * h
        brx = self.crop_borders[1][0] * w
        bry = self.crop_borders[1][1] * h
        cw = brx-tlx
        ch = bry-tly
        self.crop_rectangle = (tlx, tly, cw, ch)
        context.rectangle(0, 0, tlx, h)
        context.rectangle(brx, 0, w, h)
        context.rectangle(0, 0, w, tly)
        context.rectangle(0, bry, w, h)
        context.fill()

        # handles
        handle_width = 6 # must be even
        handle_length = min(cw/6, ch/6)
        if handle_length < 20: handle_length = 20
        self.handle_rectangles = [
            ((tlx-(handle_width/2), tly-(handle_width/2), handle_length, handle_width), "tl"),
            ((tlx-(handle_width/2), tly-(handle_width/2), handle_width, handle_length), "tl"),
            ((brx-handle_length, bry-(handle_width/2), handle_length + (handle_width/2), handle_width), "br"),
            ((brx-(handle_width/2), bry-handle_length, handle_width, handle_length + (handle_width/2)), "br")
        ]

        context.set_source_rgba(0, 128, 0, 1)
        for r, loc in self.handle_rectangles:
            context.rectangle(*r)
        context.fill()

    def remove_crop_mode(self):
        print("remove crop")
        self.btnapply.set_sensitive(False)
        self.btncrop.set_active(False)
        self.da.disconnect(self.crop_mousedown_id)
        self.da.disconnect(self.crop_mouseup_id)
        self.btnapply.disconnect(self.crop_apply_id)
        self.da.destroy()

    def crop_mousedown(self, widget, event):
        in_handle = False
        for r, loc in self.handle_rectangles:
            if in_rectangle(event, r):
                print("crop md IN", loc)
                in_handle = True
                if loc == "tl":
                    self.crop_mousemove_id = self.da.connect("motion-notify-event", self.crop_mm_tl)
                    print("Set crop mm to tl", self.crop_mousemove_id)
                else:
                    self.crop_mousemove_id = self.da.connect("motion-notify-event", self.crop_mm_br)
                    print("Set crop mm to br", self.crop_mousemove_id)
                alloc = widget.get_allocation()
                self.surface_w = alloc.width
                self.surface_h = alloc.height
                break
        if not in_handle:
            if in_rectangle(event, self.crop_rectangle):
                print("crop md IN CROP")
                alloc = widget.get_allocation()
                self.surface_w = alloc.width
                self.surface_h = alloc.height
                self.move_original_x = event.x
                self.move_original_y = event.y
                self.original_crop_rectangle = copy.copy(self.crop_rectangle)
                self.crop_mousemove_id = self.da.connect("motion-notify-event", self.crop_mm_crop)
            else:
                print("crop md NOWHERE", event.x, event.y)
    def crop_mm_tl(self, widget, event):
        new_tl = [event.x / self.surface_w, event.y / self.surface_h]

        # You can't crop to less than a tenth of the image
        if (self.crop_borders[1][0] - new_tl[0] < 0.1): return
        if (self.crop_borders[1][1] - new_tl[1] < 0.1): return

        self.crop_borders[0] = new_tl
        self.da.queue_draw()

    def crop_mm_br(self, widget, event):
        new_tl = [event.x / self.surface_w, event.y / self.surface_h]

        # You can't crop to less than a tenth of the image
        if (new_tl[0] - self.crop_borders[0][0] < 0.1): return
        if (new_tl[1] - self.crop_borders[0][1] < 0.1): return

        self.crop_borders[1] = new_tl
        self.da.queue_draw()

    def crop_mm_crop(self, widget, event):
        dx = event.x - self.move_original_x
        dy = event.y - self.move_original_y
        new_crop = [
            self.original_crop_rectangle[0] + dx,
            self.original_crop_rectangle[1] + dy,
            self.original_crop_rectangle[0] + self.original_crop_rectangle[2] + dx, 
            self.original_crop_rectangle[1] + self.original_crop_rectangle[3] + dy
        ]

        tl = [new_crop[0]/self.surface_w, new_crop[1]/self.surface_h]
        br = [new_crop[2]/self.surface_w, new_crop[3]/self.surface_h]
        self.crop_borders = [tl, br]
        self.da.queue_draw()

    def crop_mouseup(self, *args):
        if hasattr(self, "crop_mousemove_id"): self.da.disconnect(self.crop_mousemove_id)

    def bubble_chosen(self, mi, s2c):
        print("bubble chosen", s2c)

        alloc = self.fixed.get_allocation()
        self.da = Gtk.DrawingArea()
        self.da.set_size_request(alloc.width, alloc.height)
        self.da.set_events(Gdk.EventMask.BUTTON_MOTION_MASK | 
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.fixed.add(self.da)

        self.bubble_tl_br_box = [alloc.width * 0.6, alloc.height * 0.3, alloc.width * 0.8, alloc.height * 0.5]
        self.bubble_text = "LOL"

        self.da.show_all()
        self.bubble_apply_id = self.btnapply.connect("clicked", self.bubble_apply)
        self.btnapply.set_sensitive(True)
        self.bubble_resize_handle_rectangles = []
        self.bubble_mousedown_id = self.da.connect("button-press-event", self.bubble_mousedown)
        self.da.connect("draw", self.actually_draw_bubble, s2c)
        self.da.queue_draw()

    def bubble_mousedown(self, widget, event):
        print("bb md", event.x, event.y, event.time)
        self.bubble_clicked_event_details = (event.x, event.y, event.time)
        in_resize = False
        for r, loc in self.bubble_resize_handle_rectangles:
            if in_rectangle(event, r):
                print("bubble md IN RESIZE", loc)
                self.disconnects = []
                self.disconnects.append(self.da.connect("motion-notify-event", self.bubble_mm_resize, loc))
                self.disconnects.append(self.da.connect("button-release-event", self.bubble_mouseup))
                in_resize = True
                break
        if not in_resize:
            bbox = (self.bubble_tl_br_box[0], self.bubble_tl_br_box[1], 
                self.bubble_tl_br_box[2]-self.bubble_tl_br_box[0],
                self.bubble_tl_br_box[3]-self.bubble_tl_br_box[1])
            if in_rectangle(event, bbox):
                print("bubble md IN RESIZE", loc)
                self.disconnects = []
                self.disconnects.append(self.da.connect("motion-notify-event", self.bubble_mm_move, (copy.copy(self.bubble_tl_br_box), event.x, event.y)))
                self.disconnects.append(self.da.connect("button-release-event", self.bubble_mouseup))

    def bubble_mm_move(self, widget, event, data):
        original_tlbr, startx, starty = data
        dx = event.x - startx
        dy = event.y - starty
        self.bubble_tl_br_box = [
            original_tlbr[0] + dx,
            original_tlbr[1] + dy,
            original_tlbr[2] + dx,
            original_tlbr[3] + dy
        ]
        self.da.queue_draw()

    def bubble_mm_resize(self, widget, event, resize_dir):
        if resize_dir == "tl":
            self.bubble_tl_br_box[0] = event.x
            self.bubble_tl_br_box[1] = event.y
        elif resize_dir == "br":
            self.bubble_tl_br_box[2] = event.x
            self.bubble_tl_br_box[3] = event.y
        print("bb resize", resize_dir, event.x, event.y, self.bubble_tl_br_box)
        self.da.queue_draw()

    def bubble_mouseup(self, widget, event, mousemove_unbind_id=None):
        print("bb mu")
        for eid in self.disconnects: self.da.disconnect(eid)
        dx = abs(event.x - self.bubble_clicked_event_details[0])
        dy = abs(event.y - self.bubble_clicked_event_details[1])
        dt = event.time - self.bubble_clicked_event_details[2]
        if (dx < 2 and dy < 2 and dt < 100):
            self.bubble_clicked()

    def bubble_clicked(self):
        dia = Gtk.Dialog.new()
        dia.set_modal(True)
        dia.add_buttons("_OK", 0, "Cancel", 1)
        dia.set_default_response(1)
        dia.set_transient_for(self.w)
        c = dia.get_content_area()
        hb = Gtk.HBox()
        hb.pack_start(Gtk.Label("Font"), False, False, 6)
        hb.pack_start(Gtk.Label("Dropdown"), True, True, 6)
        c.pack_start(hb, False, False, 6)
        tv = Gtk.TextView.new()
        tv.set_justification(Gtk.Justification.CENTER)
        buf = tv.get_buffer()
        buf.set_text(self.bubble_text)
        c.pack_start(tv,True, True, 6)
        c.show_all()
        response = dia.run()
        print("response", response)
        if response == Gtk.ResponseType.DELETE_EVENT:
            print("closed")
        elif response == 1:
            print("cancelled")
        elif response == 0:
            bounds = buf.get_bounds()
            self.bubble_text = buf.get_text(bounds[0], bounds[1], False)
            print("ok")
        else:
            print("something else")
        dia.destroy()

    def bubble_apply(self, btn):
        print("bb apply")
    def actually_draw_bubble(self, da, context, s2c):
        print("draw", self.bubble_tl_br_box)
        # bubble_tl_br_box holds coordinates; make a standard x,y,w,h box
        bbox = (self.bubble_tl_br_box[0], self.bubble_tl_br_box[1], 
            self.bubble_tl_br_box[2]-self.bubble_tl_br_box[0],
            self.bubble_tl_br_box[3]-self.bubble_tl_br_box[1])
        print("bbox", bbox)
        details = s2c.render_to_context_at_size_with_text(context, 
            bbox[0], bbox[1], bbox[2], bbox[3], self.bubble_text, "Impact")
        context.rectangle(*bbox)
        context.set_line_width(2)
        context.set_source_rgba(255, 0, 0, 0.9)
        context.set_dash([5])
        context.stroke()

        handle_width = 6 # must be even
        handle_length = min(bbox[2]/6, bbox[3]/6)
        self.bubble_resize_handle_rectangles = (
            ((bbox[0] - (handle_width/2), bbox[1] - (handle_width/2), 
                handle_length, handle_width), "tl"), # horizontal tl
            ((bbox[0] - (handle_width/2), bbox[1] - (handle_width/2), 
                handle_width, handle_length), "tl"), # vertical tl
            ((self.bubble_tl_br_box[2] - handle_length + (handle_width/2),
              self.bubble_tl_br_box[3] - (handle_width/2),
              handle_length, handle_width), "br"), # horizontal br
            ((self.bubble_tl_br_box[2] - (handle_width/2),
              self.bubble_tl_br_box[3] - handle_length + (handle_width/2),
              handle_width, handle_length), "br") # vertical br
        )
        context.set_source_rgba(0, 128, 0, 1)
        for r, loc in self.bubble_resize_handle_rectangles:
            context.rectangle(*r)
        context.fill()

def main():
    m = Main()
    m.app.run(sys.argv)

if __name__ == "__main__": main()

