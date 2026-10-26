"""V2 three-measurement monitor UI rendered with Pillow for the RGB565 LCD."""
import math
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import colores as C
from .estado import view_model, strip_note, history_stats, chart_domain
from .tokens_v2 import C as TOKENS

S = 2
COL = {"bg":"#000000", "panel":"#0D0D0D", "line":"#5A5A5A", "track":"#2E2E2E",
       "text":"#FFFFFF", "text2":"#F2F2F2", "muted":"#D0D0D0", "ok":"#3DE07F",
       "ember":"#FF6A2B", "dew":"#2FC8FF", "sub":"#C792FF", "honey":"#FFD60A",
       "mist":"#80CBFF", "danger":"#FF5252", "nodata":"#A8A8A8", "nodata_line":"#808080",
       "on":"#000000", "zone":"#2FA15D", "band":"#173724"}
ACCENT = {"t":COL["ember"], "h":COL["dew"], "s":COL["sub"]}
RING = {"ok":COL["ok"], "high":COL["honey"], "low":COL["mist"], "disc":COL["danger"], "nodata":COL["nodata"]}


class Canvas:
    def __init__(self, size, color=COL["bg"]):
        self.image = Image.new("RGB", (size[0]*S, size[1]*S), color)
        self.d = ImageDraw.Draw(self.image)
    def b(self, box): return tuple(round(x*S) for x in box)
    def font(self, family, size): return _font(family, size*S)
    def line(self, points, fill, width=1):
        self.d.line([(round(x*S),round(y*S)) for x,y in points], fill=fill, width=max(1,round(width*S)), joint="curve")
    def box(self, box, fill, outline=None, radius=0, width=1):
        if radius: self.d.rounded_rectangle(self.b(box), round(radius*S), fill=fill, outline=outline, width=max(1,round(width*S)))
        else: self.d.rectangle(self.b(box), fill=fill, outline=outline, width=max(1,round(width*S)))
    def ellipse(self, box, fill, outline=None, width=1): self.d.ellipse(self.b(box), fill=fill, outline=outline, width=max(1,round(width*S)))
    def text(self, xy, value, family="r", size=13, color=COL["text"], anchor="la", spacing=0):
        x,y=xy; f=self.font(family,size)
        # Baseline anchoring keeps accented glyphs on the same line as the rest.
        if spacing:
            width=sum(f.getlength(ch) for ch in value)/S+spacing*(len(value)-1)
            if anchor in ("ma","mm"): x-=width/2
            elif anchor in ("ra","rm"): x-=width
            baseline=round(y*S)-f.getbbox("H",anchor="ls")[1]
            for ch in value:
                self.d.text((round(x*S),baseline),ch,font=f,fill=color,anchor="ls")
                x+=f.getlength(ch)/S+spacing
        else:
            anchor_map={"la":"ls","ma":"ms","ra":"rs","mm":"ms","rm":"rs"}
            baseline=round(y*S)-f.getbbox("H",anchor="ls")[1]
            self.d.text((round(x*S),baseline),value,font=f,fill=color,anchor=anchor_map.get(anchor,"ls"))
    def arc(self, center, radius, start, end, color, width, rounded=False):
        if end<=start: return
        x,y=center; self.d.arc(self.b((x-radius,y-radius,x+radius,y+radius)),start,end,fill=color,width=round(width*S))
        if rounded:
            rr=width/2
            for ang in (start,end):
                a=math.radians(ang); px=x+(radius-rr)*math.cos(a); py=y+(radius-rr)*math.sin(a)
                self.ellipse((px-rr,py-rr,px+rr,py+rr),color)
    def done(self): return self.image.resize((self.image.width//S,self.image.height//S),Image.Resampling.LANCZOS)


@lru_cache(maxsize=128)
def _font(family, size):
    path=Path(__file__).parent/"assets"/"fonts"/(family+".ttf")
    # The supplied v2 fonts are static weights (including Fraunces 600).
    return ImageFont.truetype(str(path),size)


class Renderer:
    def __init__(self, config=None):
        self.config=config
        self._key=None; self._frame=None
    def _model(self, k, sensors, readings):
        from .monitor import valid_value
        conf={"temp":self.config.temperature,"hum":self.config.humidity,"sub":self.config.substrate}
        cfg={name:{"min":r.minimum,"max":r.maximum,"scale_min":r.scale_min,"scale_max":r.scale_max} for name,r in conf.items()}
        vals={"t":valid_value(readings, {"sht31":sensors["sht31"]} if sensors["sht31"]!="ok" else {}, "sht31", "temperature"),
              "h":valid_value(readings, {"sht31":sensors["sht31"]} if sensors["sht31"]!="ok" else {}, "sht31", "humidity"),
              "s":valid_value(readings, {"ds18b20":sensors["ds18b20"]} if sensors["ds18b20"]!="ok" else {}, "ds18b20", "temperature")}
        return view_model(k,sensors,vals,cfg)
    @staticmethod
    def _sensor_states(errors):
        return {n:errors.get(n,"ok") for n in ("sht31","ds18b20")}
    def _header(self, image, clock, network, simulated, now):
        c=Canvas((480,44));
        # mushroom mark
        c.ellipse((17,10,38,31),COL["ok"]); c.box((16,23,39,34),COL["bg"]); c.box((24,24,30,34),COL["text2"],radius=2)
        c.text((48,12),"Monitoreo","Fraunces-600",21,COL["text"])
        if simulated: c.text((163,21),"DEMO","Barlow-700",9,COL["honey"])
        c.text((464,12),clock,"BarlowCondensed-500",24,COL["text2"],"ra",.96)
        if network.state in ("fail", "waiting", "disabled"):
            base=time.monotonic() if now is None else now
            if network.state=="fail":
                since=base if network.failed_since is None else network.failed_since
                label=f"API sin conexión · {max(1,int(max(0,base-since)//60))} min"; color=COL["honey"]
            else:
                label="API pendiente" if network.state=="waiting" else "HTTP desactivado"; color=COL["muted"]
            c.box((235,9,399,35),COL["bg"],color,13)
            c.text((317,16),label,"Barlow-600",12,color,"ma")
        else:
            # small cloud/check icon
            c.ellipse((376,18,388,28),COL["bg"],COL["ok"],1.5); c.ellipse((382,14,393,26),COL["bg"],COL["ok"],1.5)
            c.line([(379,26),(393,26)],COL["ok"],1.5); c.line([(382,22),(385,25),(391,19)],COL["ok"],1.5)
        image.paste(c.done(),(0,0))
    def _chip(self,c,x,y,label,state):
        color=RING[state]; filled=state in ("high","low","disc"); width=max(48,len(label)*7+16)
        if label=="ÓPTIMA": width=68
        if label=="SIN SENSOR": width=83
        c.box((x-width,y,x,y+26),color if filled else COL["panel"],color,13)
        c.text((x-width/2,y+6),label,"Barlow-700",11,COL["on"] if filled else color,"ma",.35)
    def _dial(self,c, x, vm, limits, title, key):
        y=44; c.box((x,y,x+228,y+220),COL["panel"],RING[vm["st"]] if vm["st"]!="ok" else COL["line"],16)
        c.text((x+15,62),title,"Barlow-600",13,COL["muted"],spacing=1.1)
        label={"ok":"ÓPTIMA","high":"ALTA","low":"BAJA","disc":"SIN SENSOR","nodata":"SIN DATO"}[vm["st"]]
        self._chip(c,x+213,55,label,vm["st"])
        cx=x+114; cy=159; k=.8; r=57.6; w=11.2
        scale=limits.scale_max-limits.scale_min
        f0=max(0,min(1,(limits.minimum-limits.scale_min)/scale)); f1=max(0,min(1,(limits.maximum-limits.scale_min)/scale))
        c.arc((cx,cy),68.8,135+270*f0,135+270*f1,COL["zone"],3.2)
        c.arc((cx,cy),63.2,135,405,COL["track"],w,True)
        if vm.get("frac") is not None:
            end=135+270*vm["frac"]; c.arc((cx,cy),63.2,135,end,ACCENT[key],w,True)
            a=math.radians(end); px=cx+r*math.cos(a); py=cy+r*math.sin(a)
            c.ellipse((px-7.2,py-7.2,px+7.2,py+7.2),COL["text"],COL["panel"],2.4)
        c.text((cx,119),vm["num"],"BarlowCondensed-600",46,COL["text"] if vm.get("v") is not None else COL["nodata"],"ma")
        c.text((cx,163),"%" if key=="h" else "°C","Barlow-600",14,COL["muted"],"ma")
        c.text((cx,180),vm["tag"],"Barlow-600",12,COL["danger"] if vm["st"]=="disc" else COL["muted"],"ma",.4)
        c.text((x+(84 if key=="h" else 80),198),f"{limits.scale_min:g}","Barlow-400",12,COL["muted"])
        c.text((x+(149 if key=="h" else 148),198),f"{limits.scale_max:g}","Barlow-400",12,COL["muted"],"ra")
        c.text((x+15,216),vm["note"],"Barlow-500",13,COL["muted"] if vm["st"]=="ok" else RING[vm["st"]])
        c.text((x+15,238),"Objetivo","Barlow-400",13,COL["muted"])
        target=f"{limits.minimum:g} – {limits.maximum:g} {'%' if key=='h' else '°C'}"
        c.text((x+213,238),target,"Barlow-600",13,COL["text2"],"ra")
    def _substrate(self,c,vm,limits):
        x,y=8,272; state=vm["st"]; edge=COL["line"] if state=="ok" else RING[state]
        c.box((x,y,x+464,y+40),COL["panel"],edge,14)
        c.text((22,279),"SUSTRATO","Barlow-600",13,COL["muted"],spacing=1)
        note=strip_note(vm,{"sub":{"min":limits.minimum,"max":limits.maximum,"scale_min":limits.scale_min,"scale_max":limits.scale_max}})
        c.text((22,295),note,"Barlow-500",11,COL["muted"] if state=="ok" else RING[state])
        val=vm["num"]
        c.text((157,276),val,"BarlowCondensed-600",28,COL["text"] if vm.get("v") is not None else COL["nodata"])
        c.text((204,286),"°C","Barlow-600",13,COL["muted"])
        left,right=248,357; yy=294; span=limits.scale_max-limits.scale_min
        z0=left+(limits.minimum-limits.scale_min)/span*(right-left); z1=left+(limits.maximum-limits.scale_min)/span*(right-left)
        c.box((z0,282,z1,286),COL["zone"],radius=2); c.box((left-7,291,right+7,299),COL["track"],radius=4)
        if vm.get("frac") is not None:
            pos=left+vm["frac"]*(right-left); c.box((left-7,291,pos,299),COL["sub"],radius=4)
            c.ellipse((pos-7,287,pos+7,301),COL["text"],COL["panel"],3)
        label={"ok":"ÓPTIMA","high":"ALTA","low":"BAJA","disc":"SIN SENSOR","nodata":"SIN DATO"}[state]
        self._chip(c,460,279,label,state)
    def _home(self, readings, errors, network, clock, now, simulated):
        image=Image.new("RGB",(480,320),COL["bg"]); self._header(image,clock,network,simulated,now)
        c=Canvas((480,320)); c.image.paste(image.resize((480*S,320*S)),(0,0))
        states=self._sensor_states(errors)
        t,h,s=(self._model(k,states,readings) for k in ("t","h","s"))
        self._dial(c,8,t,self.config.temperature,"TEMPERATURA","t")
        self._dial(c,244,h,self.config.humidity,"HUMEDAD","h")
        self._substrate(c,s,self.config.substrate)
        frame=c.done(); self._dots(frame,0); return frame
    def _card(self,c,x,w,k,vm,limits,samples):
        y=44; c.box((x,y,x+w,y+234),COL["panel"],COL["line"],16)
        title={"t":"TEMPERATURA","h":"HUMEDAD","s":"SUSTRATO"}[k]
        c.text((x+8,57),title,"Barlow-600",12,COL["muted"],spacing=.45)
        # Chart area and target band
        x0,x1=x+31,x+w-8; y0,y1=108,165; lo,hi=chart_domain(limits.minimum,limits.maximum,samples)
        py=lambda v:y1-(v-lo)*(y1-y0)/max(1e-8,hi-lo)
        fmt_axis=lambda v: f"{v:.1f}".replace(".",",") if k!="h" else str(round(v))
        c.text((x+27,y0-5),fmt_axis(hi),"Barlow-400",9,COL["muted"],"ra")
        c.text((x+27,y1-5),fmt_axis(lo),"Barlow-400",9,COL["muted"],"ra")
        top,bottom=py(limits.maximum),py(limits.minimum)
        c.box((x0,top,x1,bottom),COL["band"])
        for yy in (top,bottom):
            xx=x0
            while xx<x1: c.line([(xx,yy),(min(xx+3,x1),yy)],COL["zone"],1); xx+=6
        vals=list(samples or [None]*96); step=(x1-x0)/max(1,len(vals)-1); prev=None
        for i,v in enumerate(vals):
            point=None if v is None else (x0+i*step,py(v))
            if prev and point: c.line([prev,point],ACCENT[k],2)
            prev=point
        if vals and vals[-1] is not None:
            px=x0+(len(vals)-1)*step; yy=py(vals[-1]); c.ellipse((px-4,yy-4,px+4,yy+4),COL["text"],COL["panel"],2)
        c.text((x0,172),"−24 h","Barlow-400",10,COL["muted"])
        c.text(((x0+x1)/2,172),"−12 h","Barlow-400",10,COL["muted"],"ma")
        c.text((x1,172),"ahora","Barlow-400",10,COL["muted"],"ra")
        stats=history_stats(vals,limits.minimum,limits.maximum)
        current=vm["num"]
        p=[x+5,x+w*.34,x+w*.66,x+w-5]
        for px,label,anchor in ((p[0],"Ahora","la"),(p[1],"Mín","ma"),(p[2],"Prom","ma"),(p[3],"Máx","ra")):
            c.text((px,191),label,"Barlow-400",10,COL["muted"],anchor)
        col=COL["text"] if vm["st"]=="ok" else RING[vm["st"]]
        c.text((p[0],204),current,"BarlowCondensed-600",15,col)
        if stats:
            fmt=lambda v: (f"{v:.1f}".replace(".",",") if k!="h" else str(round(v)))
            c.text((p[1],204),fmt(stats["min"]),"BarlowCondensed-600",15,COL["text2"],"ma")
            c.text((p[2],204),fmt(stats["avg"]),"BarlowCondensed-600",15,COL["text2"],"ma")
            c.text((p[3],204),fmt(stats["max"]),"BarlowCondensed-600",15,COL["text2"],"ra")
            pct=stats["share_pct"]
        else:
            for px in p[1:]: c.text((px,204),"—","BarlowCondensed-600",15,COL["text2"],"ma")
            pct=None
        c.text((x+8,226),"En rango · 24 h","Barlow-500",12,COL["text2"])
        c.text((x+w-8,226),f"{pct} %" if pct is not None else "—","Barlow-600",12,COL["text2"],"ra")
        c.box((x+8,247,x+w-8,255),COL["track"],radius=4)
        if pct: c.box((x+8,247,x+8+(w-16)*pct/100,255),COL["ok"],radius=4)
    def _summary(self,readings,errors,network,clock,now,simulated,history):
        image=Image.new("RGB",(480,320),COL["bg"]); self._header(image,clock,network,simulated,now)
        c=Canvas((480,320)); c.image.paste(image.resize((480*S,320*S)),(0,0))
        states=self._sensor_states(errors); specs=[("t",self.config.temperature), ("h",self.config.humidity),("s",self.config.substrate)]
        samples=history or {}; keys={"t":"temperature","h":"humidity","s":"substrate"}
        for x,w,(k,limits) in zip((8,166,322),(150,148,150),specs):
            self._card(c,x,w,k,self._model(k,states,readings),limits,samples.get(keys[k],[None]*96))
        c.box((8,286,472,312),COL["panel"],COL["line"],13)
        api_state="ok" if network.state=="ok" else "warn" if network.state=="fail" else "nodata"
        items=[("Microclima",states["sht31"]), ("Sustrato",states["ds18b20"]),("API",api_state)]
        for i,(name,state) in enumerate(items):
            x=20+i*150; dot=COL["ok"] if state=="ok" else COL["danger"] if state in ("disc","warn") else COL["muted"]
            if state=="nodata": c.ellipse((x,294,x+9,303),COL["panel"],dot,2)
            else: c.ellipse((x,294,x+9,303),dot)
            suffix=("" if state=="ok" else "sin dato" if state=="nodata" else "sin sensor" if state=="disc" else "sin conexión")
            c.text((x+14,293),name,"Barlow-500",12,COL["text2"])
            if name=="API":
                base=time.monotonic() if now is None else now
                if network.state=="ok": suffix=f"envío {max(0,int(base-(network.last_success or base)))} s"
                elif network.state=="fail":
                    since=base if network.failed_since is None else network.failed_since
                    suffix=f"sin conexión {max(1,int(max(0,base-since)//60))} min"
                else: suffix="pendiente" if network.state=="waiting" else "desactivado"
            c.text((x+78,293),suffix,"Barlow-400",10,COL["honey"] if state=="warn" else COL["muted"])
        frame=c.done(); self._dots(frame,1); return frame
    @staticmethod
    def _dots(image,page):
        d=ImageDraw.Draw(image)
        d.rounded_rectangle((229,313,229+(14 if page==0 else 5),318),2,fill=COL["muted"] if page==0 else COL["nodata_line"])
        d.rounded_rectangle((246,313,246+(14 if page==1 else 5),318),2,fill=COL["muted"] if page==1 else COL["nodata_line"])
    def render(self,readings,errors,network=None,clock=None,now=None,simulated=False,page=0,history=None):
        from .monitor import NetworkStatus
        network=network or NetworkStatus(); clock=clock or datetime.now().strftime("%H:%M")
        now=time.monotonic() if now is None else now
        key=(page,repr(readings),repr(errors),network.state,network.failed_since,network.last_success,clock,simulated,
             int(now) if page else None,repr(history) if page else None)
        if key!=self._key:
            self._frame=self._summary(readings,errors,network,clock,now,simulated,history) if page else self._home(readings,errors,network,clock,now,simulated)
            self._key=key
        return self._frame
