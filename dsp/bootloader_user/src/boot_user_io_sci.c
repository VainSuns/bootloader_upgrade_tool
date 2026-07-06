#include "F28x_Project.h"
#include "boot_io.h"
#include "boot_user_io_sci.h"


static void BootSci_RecoverRxError(void);


/*
 * USER ACTION REQUIRED:
 * - bind ctx to the product SCI driver state;
 * - perform the ASCII 'A' autobaud exchange inside connect_master;
 * - enforce timeout_ms locally without creating a protocol timeout status;
 * - convert two wire bytes (low byte first) to/from one protocol word.
 *
 * Do not add protocol framing or ACK/NAK handling here.
 */

void BootSCI_Init()
{
    //
    // Enable the SCI-A clocks
    //
    EALLOW;

    CpuSysRegs.PCLKCR7.bit.SCI_A = 1;
    ClkCfgRegs.LOSPCP.all = 0x0007;

    /*
     * Put SCI in reset while configuring.
     */
    SciaRegs.SCICTL1.all = 0x0000;

    /*
     * 1 stop bit, no parity, 8-bit character, no loopback.
     */
    SciaRegs.SCICCR.all = 0x0007;

    /*
     * Enable TX, RX, internal SCICLK.
     */
    SciaRegs.SCICTL1.all = 0x0003;

    /*
     * Disable RX/TX interrupts.
     */
    SciaRegs.SCICTL2.all = 0x0000;

    /*
     * Enable FIFO.
     *
     * SCIFFTX = 0xE040:
     *   SCIRST       = 1
     *   SCIFFENA     = 1
     *   TXFIFOXRESET = 1
     *   TXFFINTCLR   = 1
     *   TXFFIENA     = 0
     *   TXFFIL       = 0
     *
     * SCIFFRX = 0x6040:
     *   RXFFOVRCLR   = 1
     *   RXFIFORESET  = 1
     *   RXFFINTCLR   = 1
     *   RXFFIENA     = 0
     *   RXFFIL       = 0
     *
     * SCIFFCT = 0x0000:
     *   no FIFO transfer delay
     *   autobaud disabled
     */
    SciaRegs.SCIFFTX.all = 0xE040;
    SciaRegs.SCIFFRX.all = 0x6040;
    SciaRegs.SCIFFCT.all = 0x0000;

    /*
     * Release SCI from reset.
     * 0x0023 = SWRESET + TXENA + RXENA.
     */
    SciaRegs.SCICTL1.all = 0x0023;
    
    EDIS;

    //
    // Configure gpio pins for SCI-A functionality
    //
    EALLOW;
    GpioCtrlRegs.GPCMUX1.bit.GPIO64 = 2;
    GpioCtrlRegs.GPCMUX1.bit.GPIO65 = 2;
    GpioCtrlRegs.GPCGMUX1.bit.GPIO64 = 1;
    GpioCtrlRegs.GPCGMUX1.bit.GPIO65 = 1;
    GpioCtrlRegs.GPCDIR.bit.GPIO64 = 0; // RX
    GpioCtrlRegs.GPCDIR.bit.GPIO65 = 1; // TX
    GpioCtrlRegs.GPCPUD.bit.GPIO64 = 0; // Enable pull-up on RX
    GpioCtrlRegs.GPCPUD.bit.GPIO65 = 0; // Enable pull-up on TX
    GpioCtrlRegs.GPCQSEL1.bit.GPIO64 = 3; // Asynch input RX
    GpioCtrlRegs.GPCQSEL1.bit.GPIO65 = 3; // Asynch input TX
    EDIS;
    
    return;
}

static uint16_t BootSci_GetByte(void *ctx)
{
    (void)ctx;

    for (;;)
    {
        if ((SciaRegs.SCIRXST.bit.RXERROR != 0U) || (SciaRegs.SCIFFRX.bit.RXFFOVF != 0U))
        {
            BootSci_RecoverRxError();
            continue;
        }

        if (SciaRegs.SCIFFRX.bit.RXFFST != 0U)
        {
            return ((uint16_t)SciaRegs.SCIRXBUF.bit.SAR & 0x00FFU);
        }
    }
}

static uint16_t BootSci_GetWord(void *ctx)
{
    uint16_t low; 
    uint16_t high;

    low = BootSci_GetByte(ctx);
    high = BootSci_GetByte(ctx);

    return (uint16_t)(low | (uint16_t)(high << 8U));
}

static void BootSci_WaitTxFifoSpace(uint16_t required_bytes)
{
    while ((16U - SciaRegs.SCIFFTX.bit.TXFFST) < required_bytes)
    {
    }
}

static void BootSci_SendWord(void *ctx, uint16_t word)
{
    (void)ctx;

    /*
     * SCI TX FIFO depth is 16 bytes. One protocol word is transmitted as
     * two bytes: low byte first, then high byte.
     */
    BootSci_WaitTxFifoSpace(2U);
    SciaRegs.SCITXBUF.bit.TXDT = (word & 0x00FFU);
    SciaRegs.SCITXBUF.bit.TXDT = ((word >> 8U) & 0x00FFU);
}

BootIoConnectResult BootSci_CreateIoOps(void *ctx, BootIoOps *ops)
{
    if (ops == NULL)
    {
        return BOOT_IO_CONNECT_FAILED;
    }

    ops->ctx = ctx;
    ops->get_word = BootSci_GetWord;
    ops->send_word = BootSci_SendWord;
    ops->get_byte = BootSci_GetByte;
    return BOOT_IO_CONNECT_OK;
}

void BootSci_ConnectStartup(void)
{
    //
    // Must prime baud register with >= 1
    //
    SciaRegs.SCIHBAUD.bit.BAUD = 0;
    SciaRegs.SCILBAUD.bit.BAUD = 1;

    //
    // Prepare for autobaud detection
    // Set the CDC bit to enable autobaud detection
    // and clear the ABD bit
    //
    SciaRegs.SCIFFCT.bit.CDC = 1;
    SciaRegs.SCIFFCT.bit.ABDCLR = 1;
}

BootIoConnectResult BootSci_ConnectFinish(void)
{
    uint16_t byteData;
    if (SciaRegs.SCIFFCT.bit.ABD == 1)
    {
        //
        // After autobaud lock, clear the ABD and CDC bits
        //
        SciaRegs.SCIFFCT.bit.ABDCLR = 1;
        SciaRegs.SCIFFCT.bit.CDC = 0;

        byteData = BootSci_GetByte(NULL);
        while (byteData != 'A')
        {
            byteData = BootSci_GetByte(NULL);
        }
        SciaRegs.SCITXBUF.bit.TXDT = byteData;
        BootSci_Flush();

        while(SciaRegs.SCIFFRX.bit.RXFFST != 0)
        {
            byteData = BootSci_GetByte(NULL);
        }

        return BOOT_IO_CONNECT_OK;
    }
    else
    {
        //
        // Autobaud detection failed
        //
        return BOOT_IO_CONNECT_FAILED;
    }
}

void BootSci_ConnectShutdown(void)
{

}

static void BootSci_RecoverRxError(void)
{
    volatile uint16_t discard;
    /*
     * 1. Drain RX FIFO.
     */
    while (SciaRegs.SCIFFRX.bit.RXFFST != 0U)
    {
        discard = (uint16_t)SciaRegs.SCIRXBUF.bit.SAR;
        (void)discard;
    }

    /*
     * 2. Clear RX FIFO overflow and interrupt flag.
     *    Keep FIFO enabled and RX FIFO released.
     *
     * SCIFFRX = 0x6040:
     *   RXFFOVRCLR  = 1
     *   RXFIFORESET = 1
     *   RXFFINTCLR  = 1
     *   RXFFIL      = 0
     */
    SciaRegs.SCIFFRX.all = 0x6040;

    /*
     * 3. Clear receiver error latch by SCI software reset.
     *    Preserve TX/RX enable after reset.
     */
    SciaRegs.SCICTL1.bit.SWRESET = 0U;
    asm(" RPT #7 || NOP");
    SciaRegs.SCICTL1.bit.SWRESET = 1U;
}
