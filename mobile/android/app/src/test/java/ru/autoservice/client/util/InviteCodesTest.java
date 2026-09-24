package ru.autoservice.client.util;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

public class InviteCodesTest {

    @Test
    public void linkFromQr() {
        assertEquals("AB12CD", InviteCodes.parse("https://moiservis.pro/i/ab12cd"));
        assertEquals("AB12CD", InviteCodes.parse("https://moiservis.pro/i/AB12CD/"));
    }

    @Test
    public void webAppLinkWithInvite() {
        assertEquals("XY9Z01", InviteCodes.parse("https://moiservis.pro/app/?install=1&invite=XY9Z01"));
    }

    @Test
    public void bareCode() {
        assertEquals("Q7W8E9", InviteCodes.parse("  q7w8e9 "));
    }

    @Test
    public void foreignQrIsNotAnInvite() {
        assertNull(InviteCodes.parse("WIFI:S:home;P:12345678;;"));
        assertNull(InviteCodes.parse("https://ya.ru/"));
        assertNull(InviteCodes.parse(""));
        assertNull(InviteCodes.parse(null));
    }

    @Test
    public void playInstallReferrer() {
        assertEquals("AB12CD", InviteCodes.fromReferrer("invite=AB12CD"));
        assertEquals("AB12CD", InviteCodes.fromReferrer("utm_source=site&invite=ab12cd&utm_medium=x"));
        assertNull(InviteCodes.fromReferrer("utm_source=google-play&utm_medium=organic"));
        assertNull(InviteCodes.fromReferrer(null));
    }
}
