"""AI Content Generator — OpenAI/Gemini backed."""
import logging
from typing import Optional
log = logging.getLogger(__name__)

class AIContentGenerator:
    """
    Generates SEO-optimised content for YouTube and Instagram using OpenAI.
    Falls back to rule-based templates when no API key is configured.
    """
    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model   = model
        self._client = None
        if api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=api_key)
                log.info("ai_generator.live", model=model)
            except Exception as e:
                log.warning(f"ai_generator.fallback: {e}")

    @property
    def _live(self) -> bool:
        return self._client is not None

    def _ask(self, system: str, user: str, max_tokens: int = 500) -> str:
        if not self._live:
            return ""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role":"system","content":system},{"role":"user","content":user}],
                max_tokens=max_tokens, temperature=0.7,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.error(f"ai_generator.error: {e}")
            return ""

    # ── YouTube ───────────────────────────────────────────────────────────────

    def youtube_title(self, topic: str, style: str = "engaging") -> dict:
        """Generate 5 YouTube title variations for a topic."""
        sys_p = "You are an expert YouTube SEO copywriter. Generate click-worthy, SEO-optimised titles."
        user_p = f"Generate 5 {style} YouTube video titles for the topic: '{topic}'. Return one per line, no numbering."
        ai_result = self._ask(sys_p, user_p, 300)
        if ai_result:
            titles = [t.strip() for t in ai_result.split("\n") if t.strip()]
        else:
            titles = self._fallback_titles(topic)
        return {"mode": "live" if self._live else "simulation", "topic": topic, "titles": titles}

    def youtube_description(self, title: str, keywords: list[str] = None) -> dict:
        """Generate a full SEO YouTube description."""
        kw = ", ".join(keywords or [title])
        sys_p = "You are a YouTube SEO expert. Write descriptions that rank well and drive engagement."
        user_p = (f"Write a compelling YouTube video description for: '{title}'. "
                  f"Include keywords: {kw}. Add timestamps placeholders, subscribe CTA, and 3 relevant hashtags. Max 400 words.")
        result = self._ask(sys_p, user_p, 600)
        if not result:
            result = self._fallback_description(title, kw)
        return {"mode": "live" if self._live else "simulation", "title": title, "description": result}

    def youtube_tags(self, topic: str, count: int = 20) -> dict:
        """Generate SEO tags for a YouTube video."""
        sys_p = "You are a YouTube SEO specialist. Generate relevant, high-search-volume tags."
        user_p = f"Generate {count} YouTube tags for: '{topic}'. Return comma-separated, no spaces around commas."
        result = self._ask(sys_p, user_p, 200)
        tags = [t.strip() for t in result.split(",")] if result else self._fallback_tags(topic)
        return {"mode": "live" if self._live else "simulation", "topic": topic, "tags": tags[:count]}

    def youtube_script(self, topic: str, duration_minutes: int = 5) -> dict:
        """Generate a YouTube video script."""
        sys_p = "You are a professional YouTube scriptwriter. Write engaging, structured scripts."
        user_p = (f"Write a {duration_minutes}-minute YouTube video script about '{topic}'. "
                  "Include: Hook (30s), Intro, 3 main points with examples, CTA outro. "
                  "Format with [SECTION] headers.")
        result = self._ask(sys_p, user_p, 1500)
        if not result:
            result = f"[HOOK]\nHook your audience with a compelling question about {topic}...\n\n[INTRO]\nWelcome back! Today we're covering {topic}...\n\n[MAIN CONTENT]\n1. First key point about {topic}...\n2. Second key point...\n3. Third key point...\n\n[OUTRO]\nThanks for watching! Like, subscribe, and comment below!"
        return {"mode": "live" if self._live else "simulation", "topic": topic, "script": result}

    # ── Instagram ─────────────────────────────────────────────────────────────

    def instagram_caption(self, topic: str, tone: str = "engaging", include_hashtags: bool = True) -> dict:
        """Generate an Instagram caption with optional hashtags."""
        sys_p = "You are an Instagram content expert. Write captions that drive engagement and follows."
        ht = " Include 20-25 relevant hashtags at the end." if include_hashtags else ""
        user_p = f"Write a {tone} Instagram caption for: '{topic}'.{ht} Max 2000 characters."
        result = self._ask(sys_p, user_p, 500)
        if not result:
            result = self._fallback_caption(topic, include_hashtags)
        return {"mode": "live" if self._live else "simulation", "topic": topic, "caption": result}

    def instagram_hashtags(self, niche: str, count: int = 30) -> dict:
        """Generate a targeted hashtag set for maximum Instagram reach."""
        sys_p = "You are an Instagram growth expert. Generate hashtags that balance reach and engagement."
        user_p = (f"Generate {count} Instagram hashtags for the niche: '{niche}'. "
                  "Mix: 5 mega (1M+), 10 large (100k-1M), 10 medium (10k-100k), 5 small (<10k). "
                  "Return comma-separated with # prefix.")
        result = self._ask(sys_p, user_p, 300)
        hashtags = [h.strip() for h in result.split(",")] if result else self._fallback_hashtags(niche)
        return {"mode": "live" if self._live else "simulation", "niche": niche, "hashtags": hashtags[:count]}

    def instagram_bio(self, niche: str, name: str = "", cta: str = "Follow for daily tips") -> dict:
        """Generate an optimised Instagram bio."""
        sys_p = "You are an Instagram profile optimisation expert."
        user_p = f"Write an optimised Instagram bio for a {niche} account{' named ' + name if name else ''}. CTA: '{cta}'. Max 150 chars. Use emojis. Include value proposition."
        result = self._ask(sys_p, user_p, 200)
        if not result:
            result = f"🚀 {niche.title()} enthusiast\n💡 Daily tips & tricks\n📈 Helping you grow\n👇 {cta}"
        return {"mode": "live" if self._live else "simulation", "niche": niche, "bio": result}

    def content_ideas(self, niche: str, platform: str = "both", count: int = 10) -> dict:
        """Generate content ideas for a niche."""
        sys_p = "You are a creative content strategist for social media."
        user_p = (f"Generate {count} unique content ideas for the {niche} niche on {platform}. "
                  "For each idea include: title, format (video/reel/post), hook, and expected engagement type. "
                  "Format as: [IDEA N] Title | Format | Hook | Engagement")
        result = self._ask(sys_p, user_p, 800)
        ideas = []
        if result:
            for line in result.split("\n"):
                line = line.strip()
                if "|" in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 2:
                        title = parts[0].lstrip("[IDEAideaIDEA0123456789] ").strip()
                        ideas.append({"title": title, "format": parts[1] if len(parts)>1 else "", "hook": parts[2] if len(parts)>2 else "", "engagement": parts[3] if len(parts)>3 else ""})
        if not ideas:
            ideas = [{"title": f"{niche.title()} tip #{i+1}", "format": "video" if i%2==0 else "reel", "hook": f"Did you know about {niche}?", "engagement": "saves"} for i in range(count)]
        return {"mode": "live" if self._live else "simulation", "niche": niche, "ideas": ideas}

    # ── Fallbacks (no API key) ────────────────────────────────────────────────

    def _fallback_titles(self, topic: str) -> list[str]:
        return [
            f"The Ultimate Guide to {topic} in 2024",
            f"I Tested {topic} for 30 Days — Here's What Happened",
            f"{topic}: Everything You Need to Know",
            f"Why Everyone Is Talking About {topic}",
            f"How to Master {topic} (Step-by-Step)",
        ]

    def _fallback_description(self, title: str, kw: str) -> str:
        return f"""In this video, we explore {title}.\n\n📌 What you'll learn:\n- Key insights about {kw}\n- Practical tips you can apply today\n- Expert advice to get better results\n\n⏱ Timestamps:\n0:00 - Introduction\n1:00 - Main Content\n4:00 - Conclusion\n\n👍 Like this video if you found it helpful!\n🔔 Subscribe for more content!\n\n#{kw.replace(', ', ' #')}"""

    def _fallback_tags(self, topic: str) -> list[str]:
        return [topic, f"{topic} tutorial", f"{topic} tips", f"how to {topic}", f"best {topic}", f"{topic} 2024", f"{topic} guide", f"learn {topic}", f"{topic} for beginners", f"{topic} explained"]

    def _fallback_caption(self, topic: str, hashtags: bool) -> str:
        caption = f"✨ {topic} is changing everything!\n\nHere's what you need to know:\n\n1️⃣ It matters more than you think\n2️⃣ The key is consistency\n3️⃣ Results come with time\n\nDouble tap if you agree! 👇"
        if hashtags:
            caption += f"\n\n#{topic.replace(' ','').lower()} #tips #motivation #growth #success #mindset #lifestyle #goals #inspire #trending"
        return caption

    def _fallback_hashtags(self, niche: str) -> list[str]:
        n = niche.lower().replace(" ", "")
        return [f"#{n}", f"#{n}tips", f"#{n}life", f"#{n}community", "#motivation", "#success", "#growth", "#trending", "#viral", "#explore", "#instagood", "#instagram", "#reels", "#content", "#creator"]