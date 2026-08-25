package com.rokidhub.nexus.plugin.codex

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HudProjectLabelTest {
    @Test fun projectIsShownBeforeTheHint() = assertEquals(
        "Проект: RokidHub  ·  Исходники остаются на ПК",
        HudProjectLabel.footer("RokidHub", "Исходники остаются на ПК"),
    )

    @Test fun absolutePathsAreNeverShown() {
        assertNull(HudProjectLabel.normalize("C:\\Users\\Azat\\secret"))
        assertEquals("Слушаю…", HudProjectLabel.footer("C:\\secret", "Слушаю…"))
    }

    @Test fun longNamesAreBoundedForTheOpticalHud() {
        assertEquals(48, HudProjectLabel.normalize("x".repeat(100))?.length)
    }
}
