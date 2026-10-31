/**
 * Set the open-ness of the aperture.
 * 
 * @param {number} openness a number from 0 to 1, where 1 is fully open 
 *                          and 0 is fully closed.
 */
function setAperture(openness) {
    openness = openness * -35 + -5
    openness = Math.max(openness, -40)
    openness = Math.min(openness, -5)
    
    const el = document.querySelector("div.logo")
    el.style.setProperty("--aperture-size", `${Math.round(openness)}deg`)
}

// Just a little woo-wah on startup.
document.addEventListener("DOMContentLoaded", () => {

    setAperture(0)
    setTimeout(() => {
        setAperture(1)
        setTimeout(() => {
            setAperture(0.65)
            setTimeout(() => {
                setAperture(0.95)

                const el = document.querySelector("div.logo")
                el.addEventListener("mouseenter", () => setAperture(0))
                el.addEventListener("mouseleave", () => setAperture(1))
            }, 400)
        }, 400)
    }, 400) 

    setInterval(() => {
        setAperture(0)
        setTimeout(() => {
            setAperture(1)
            setTimeout(() => {
                setAperture(0.65)
                setTimeout(() => {
                    setAperture(0.95)

                    const el = document.querySelector("div.logo")
                    el.addEventListener("mouseenter", () => setAperture(0))
                    el.addEventListener("mouseleave", () => setAperture(1))
                }, 400)
            }, 400)
        }, 400)   
    }, 60_000)
})
