package ru.autoservice.client.data.remote;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.domain.model.Models;

/** Итог к оплате в «Моих записях»: правка мастера и сервер постарше без поля. */
public class DtoMapperBookingTest {

    private static Dtos.BookingDto dto() {
        Dtos.BookingDto dto = new Dtos.BookingDto();
        dto.id = "1";
        dto.code = "ABC123";
        dto.status = "completed";
        dto.oilPrice = "3900.00";
        dto.workPrice = "900.00";
        dto.totalPrice = "4800.00";
        dto.pointsSpent = "1000.00";
        return dto;
    }

    @Test
    public void finalPriceFromMasterIsShownAndPaidIsCountedFromIt() {
        Dtos.BookingDto dto = dto();
        dto.finalPrice = "5300.00";
        dto.priceChanged = true;

        Models.Booking booking = DtoMapper.booking(dto);

        assertEquals(4800.0, booking.totalPrice(), 0.001);
        assertEquals(5300.0, booking.finalPrice(), 0.001);
        assertTrue(booking.priceChanged());
        assertEquals(4300.0, booking.paidAmount(), 0.001);
    }

    @Test
    public void olderServerWithoutFinalPriceFallsBackToBookingPrice() {
        Models.Booking booking = DtoMapper.booking(dto());

        assertEquals(4800.0, booking.finalPrice(), 0.001);
        assertFalse(booking.priceChanged());
        assertEquals(3800.0, booking.paidAmount(), 0.001);
    }
}
