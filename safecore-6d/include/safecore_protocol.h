// safecore_protocol.h

#pragma pack(push, 1)
typedef struct {
    uint8_t  sync;          // 0xA5 (marca de início)
    uint8_t  cmd;           // 0x01 = solicitar métricas, 0x02 = enviar regime
    uint32_t timestamp;     // tempo em ms
    float    phi;           // coerência (Φ)
    float    tau;           // tensão (τ)
    float    z;             // função de partição (Z)
    uint8_t  regime;        // 0=Maintain, 1=Explore, 2=Decouple, 3=Quench
    uint16_t checksum;      // CRC16 sobre os dados
} ConstitutionalPacket;
#pragma pack(pop)

typedef enum {
    REGIME_MAINTAIN = 0,
    REGIME_EXPLORE = 1,
    REGIME_DECOUPLE = 2,
    REGIME_QUENCH = 3
} RegimeAction;