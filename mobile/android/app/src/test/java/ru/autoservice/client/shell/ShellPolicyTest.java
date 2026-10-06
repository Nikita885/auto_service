package ru.autoservice.client.shell;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Какие адреса оболочка открывает у себя — и, значит, кому достаётся мост
 * к токенам. Ошибка здесь не падает, а тихо отдаёт мост чужой странице.
 */
public class ShellPolicyTest {

    private final ShellPolicy prod = new ShellPolicy("https://moi-servis.ru/");

    @Test
    public void startsAtWebApp() {
        assertEquals("https://moi-servis.ru/app/", prod.startUrl());
        assertEquals("http://10.0.2.2:8000/app/", new ShellPolicy("http://10.0.2.2:8000").startUrl());
    }

    @Test
    public void webAppIsInternal() {
        assertTrue(prod.isInternal("https://moi-servis.ru/app/"));
        assertTrue(prod.isInternal("https://moi-servis.ru/app/#bookings"));
        assertTrue(prod.isInternal("https://moi-servis.ru/app/?invite=ABC123"));
        assertTrue(prod.isInternal("https://moi-servis.ru/app"));
        assertTrue(prod.isInternal("HTTPS://MOI-SERVIS.RU/app/"));
        assertTrue(prod.isInternal("https://moi-servis.ru:443/app/"));
    }

    @Test
    public void restOfSiteOpensInBrowser() {
        assertFalse(prod.isInternal("https://moi-servis.ru/"));
        assertFalse(prod.isInternal("https://moi-servis.ru/i/ABC123"));
        assertFalse(prod.isInternal("https://moi-servis.ru/application/"));
        assertFalse(prod.isInternal("https://moi-servis.ru/admin/"));
    }

    @Test
    public void lookalikesAreForeign() {
        assertFalse(prod.isInternal("https://moi-servis.ru.evil.example/app/"));
        assertFalse(prod.isInternal("https://evil.example/app/?https://moi-servis.ru/app/"));
        assertFalse(prod.isInternal("https://evil.example/moi-servis.ru/app/"));
        assertFalse(prod.isInternal("https://www.moi-servis.ru/app/"));
        assertFalse(prod.isInternal("http://moi-servis.ru/app/"));  // без TLS — не свой
        assertFalse(prod.isInternal("https://moi-servis.ru:8443/app/"));
        assertFalse(prod.isInternal("tel:+79001234567"));
        assertFalse(prod.isInternal("javascript:alert(1)"));
        assertFalse(prod.isInternal("not a url"));
        assertFalse(prod.isInternal(null));
    }

    @Test
    public void debugServerWithPort() {
        ShellPolicy local = new ShellPolicy("http://10.0.2.2:8765/");
        assertTrue(local.isInternal("http://10.0.2.2:8765/app/"));
        assertFalse(local.isInternal("http://10.0.2.2:8000/app/"));
    }

    @Test
    public void onlyClientTokensGoToKeystore() {
        assertEquals("access", ShellPolicy.storageKey("client.access"));
        assertEquals("refresh", ShellPolicy.storageKey("client.refresh"));
        assertNull(ShellPolicy.storageKey("staff.access"));
        assertNull(ShellPolicy.storageKey("client.invite"));
        assertNull(ShellPolicy.storageKey(null));
    }
}
