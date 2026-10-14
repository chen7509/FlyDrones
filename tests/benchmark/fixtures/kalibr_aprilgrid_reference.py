# Upstream test reference; see third_party/kalibr-aprilgrid/LICENSE and NOTICE.txt.
def generateAprilTag(canvas, position, metricSize, tagSpacing, tagID, tagFamililyData, rotation=2, symmCorners=True, borderBits=2):
    #get the tag code
    try:
        tagCode=tagFamililyData.tagCodes[tagID]
    except:
        print("[ERROR]: Requested tag ID of {0} not available in the {1} TagFamiliy".format(tagID, tagFamililyData.chosenTagFamiliy))        

    #calculate the bit size of the tag
    sqrtBits = (math.sqrt(tagFamililyData.totalBits))
    bitSquareSize = metricSize / (sqrtBits+borderBits*2)
    
    #position of tag
    xPos = position[0]
    yPos = position[1]
    
    #borders (2x bit size)
    borderSize = borderBits*bitSquareSize

    c.fill(path.rect(xPos, yPos, metricSize, borderSize),[color.rgb.black]) #bottom
    c.fill(path.rect(xPos, yPos+metricSize-borderSize, metricSize, borderSize),[color.rgb.black]) #top
    c.fill(path.rect(xPos+metricSize-borderSize, yPos, borderSize, metricSize),[color.rgb.black]) #left
    c.fill(path.rect(xPos, yPos, borderSize, metricSize),[color.rgb.black]) #right
    
    #create numpy matrix of code
    codeMatrix = np.zeros((int(sqrtBits), int(sqrtBits)))
    for i in range(0, int(sqrtBits)):
        for j in range(0, int(sqrtBits)):
            if not tagCode & (1 << int(sqrtBits)*i+j):
                codeMatrix[i,j] = 1 
                 
    #rotation
    codeMatrix = np.rot90(codeMatrix, rotation)
    
    #bits
    for i in range(0, int(sqrtBits)):
        for j in range(0, int(sqrtBits)):
            if codeMatrix[i,j]:
                c.fill(path.rect(xPos+(j+borderBits)*bitSquareSize, yPos+((borderBits-1)+sqrtBits-i)*bitSquareSize, bitSquareSize, bitSquareSize),[color.rgb.black])
                
    #add squares to make corners symmetric (decreases the effect of motion blur in the subpix refinement...)
    if symmCorners:
        metricSquareSize = tagSpacing*metricSize
        
        corners = [ 
                    [xPos-metricSquareSize, yPos-metricSquareSize ],
                    [xPos+metricSize, yPos-metricSquareSize],
                    [xPos+metricSize, yPos+metricSize],
                    [xPos-metricSquareSize, yPos+metricSize] 
                  ]
        
        for point in corners:
            c.fill(path.rect(point[0], point[1], metricSquareSize, metricSquareSize),[color.rgb.black])
